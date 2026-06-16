"""Candidate-bound pre-execution evidence for stealth command contracts."""

from __future__ import annotations

from core.enums import (
    AdminApiGateStatus,
    AdminApiLivePreflightCategory,
    AdminApiStealthDecisionResolutionEvidenceType,
    AdminApiStealthLiveReadinessDecision,
)

from .models import (
    AdminLivePreflightCheckItem,
    StealthExecutionBackendDecisionEvidence,
    StealthExecutionBackendDecisionResolutionSummary,
    StealthExecutionCandidateEvidence,
    StealthExecutionDecisionResolutionClearanceAction,
    StealthExecutionDecisionResolutionClearanceDependencySummary,
    StealthExecutionDecisionResolutionHandoff,
    StealthExecutionDecisionResolutionReadinessItem,
    StealthExecutionDecisionResolutionReadinessSummary,
    StealthExecutionLiveReadinessEvidence,
    StealthExecutionPreflightEvidence,
    StealthExecutionTransitionBarrierEvidence,
)


_STEALTH_LIVE_READINESS_DECISIONS = [
    AdminApiStealthLiveReadinessDecision.EXPLICIT_LIVE_ENABLEMENT,
    AdminApiStealthLiveReadinessDecision.BACKEND_LIVE_SERVICE_CONFIGURATION,
    AdminApiStealthLiveReadinessDecision.BACKEND_LIVE_ADAPTER_CONSTRUCTION,
    AdminApiStealthLiveReadinessDecision.MANAGER_INVOCATION_POLICY,
    AdminApiStealthLiveReadinessDecision.COINBASE_EXCHANGE_SUBMISSION_POLICY,
    AdminApiStealthLiveReadinessDecision.POST_WRITE_RECONCILIATION_EXECUTION_POLICY,
    AdminApiStealthLiveReadinessDecision.STATE_MUTATION_POLICY,
]

_STEALTH_LIVE_READINESS_DECISION_METADATA = {
    AdminApiStealthLiveReadinessDecision.EXPLICIT_LIVE_ENABLEMENT: {
        "owner": "admin_api_contract",
        "required_artifact": "explicit_backend_live_enablement_decision",
        "missing_reason": "explicit_live_enablement_decision_missing",
        "resolution_artifacts": [
            "explicit_backend_live_enablement_decision",
            "route_bound_approval_snapshot",
            "route_bound_admission_audit",
            "route_bound_cap_guard_decision",
            "route_bound_reconciliation_plan",
        ],
        "resolution_contract_refs": [
            "POST /api/v1/admin/approvals/requests",
            "POST /api/v1/admin/approvals/requests/{approval_request_id}/decisions",
            "POST /api/v1/admin/admission-audits",
            "POST /api/v1/admin/cap-guard/decisions",
            "POST /api/v1/admin/reconciliation/plans",
        ],
        "resolution_evidence_refs": [
            "stealth_admission_context",
            "execution_preflight",
            "execution_transition_barrier",
            "execution_live_readiness",
        ],
        "resolution_plan_steps": [
            "capture_route_bound_operator_approval",
            "verify_admission_audit_cap_guard_and_reconciliation_plan",
            "record_backend_live_enablement_decision",
        ],
        "resolution_dependency_refs": [
            "route_bound_approval_snapshot",
            "route_bound_admission_audit",
            "route_bound_cap_guard_decision",
            "route_bound_reconciliation_plan",
        ],
        "resolution_verification_gates": [
            "approval_snapshot_approved",
            "cap_guard_within_configured_limits",
            "admission_audit_recorded_for_exact_context",
            "reconciliation_plan_present_before_live_enablement",
        ],
        "resolution_handoff_categories": [
            AdminApiLivePreflightCategory.APPROVAL,
            AdminApiLivePreflightCategory.AUDIT,
            AdminApiLivePreflightCategory.CAP_GUARD,
            AdminApiLivePreflightCategory.RECONCILIATION,
            AdminApiLivePreflightCategory.BROWSER_AUTHORITY,
        ],
        "detail": (
            "A backend-owned live enablement decision must explicitly allow the "
            "route before any stealth command can become executable."
        ),
    },
    AdminApiStealthLiveReadinessDecision.BACKEND_LIVE_SERVICE_CONFIGURATION: {
        "owner": "runtime_lifecycle",
        "required_artifact": "configured_admin_api_live_execution_service",
        "missing_reason": "backend_live_service_configuration_missing",
        "resolution_artifacts": [
            "configured_admin_api_live_execution_service",
            "runtime_live_service_configuration",
            "deployment_live_service_enablement_record",
        ],
        "resolution_contract_refs": [
            "application/admin_api/live_execution.py::AdminApiLiveExecutionService",
            "application/admin_api/live_execution.py::DisabledAdminApiLiveExecutionService",
        ],
        "resolution_evidence_refs": [
            "live_execution_service_contract",
            "admin_live_enablement.paths",
        ],
        "resolution_plan_steps": [
            "configure_admin_api_live_execution_service",
            "bind_runtime_live_service_configuration",
            "record_deployment_live_service_enablement",
        ],
        "resolution_dependency_refs": [
            "admin_live_enablement.paths",
            "runtime_live_service_configuration",
            "deployment_live_service_enablement_record",
        ],
        "resolution_verification_gates": [
            "live_service_configuration_is_backend_owned",
            "browser_and_bff_do_not_hold_live_switch",
            "disabled_service_contract_replaced_by_reviewed_live_service",
        ],
        "resolution_handoff_categories": [
            AdminApiLivePreflightCategory.LIVE_EXECUTION_SERVICE,
        ],
        "detail": (
            "The Admin API live execution service must be configured by the "
            "backend; browser or BFF state cannot satisfy this decision."
        ),
    },
    AdminApiStealthLiveReadinessDecision.BACKEND_LIVE_ADAPTER_CONSTRUCTION: {
        "owner": "admin_api_contract",
        "required_artifact": "route_bound_stealth_live_execution_adapter",
        "missing_reason": "backend_live_adapter_construction_missing",
        "resolution_artifacts": [
            "route_bound_stealth_live_execution_adapter",
            "shared_command_service_adapter",
            "route_inventory_execution_binding",
        ],
        "resolution_contract_refs": [
            "application/admin_api/live_execution.py::build_live_execution_adapter_contract",
            "application/admin_api/command_service.py::AdminApiCommandService",
            "application/admin_api/route_inventory.py",
        ],
        "resolution_evidence_refs": [
            "live_execution_adapter_contract",
            "canonical_execution_path",
            "execution_candidate",
        ],
        "resolution_plan_steps": [
            "bind_route_to_shared_command_service_adapter",
            "prove_adapter_uses_canonical_execution_path",
            "reject_route_local_executor",
        ],
        "resolution_dependency_refs": [
            "route_bound_stealth_live_execution_adapter",
            "shared_command_service_adapter",
            "route_inventory_execution_binding",
        ],
        "resolution_verification_gates": [
            "adapter_is_route_bound",
            "adapter_calls_shared_command_service_only",
            "no_parallel_manager_or_coinbase_path_exists",
        ],
        "resolution_handoff_categories": [
            AdminApiLivePreflightCategory.LIVE_EXECUTION_ADAPTER,
        ],
        "detail": (
            "A route-bound backend adapter must exist before the shared command "
            "service can be invoked for live stealth execution."
        ),
    },
    AdminApiStealthLiveReadinessDecision.MANAGER_INVOCATION_POLICY: {
        "owner": "stealth_lifecycle",
        "required_artifact": "stealth_manager_invocation_policy",
        "missing_reason": "manager_invocation_policy_missing",
        "resolution_artifacts": [
            "stealth_manager_invocation_policy",
            "mutation_lock_policy",
            "exchange_reality_invariant_policy",
        ],
        "resolution_contract_refs": [
            "core/stealth_order_manager.py",
            "business/stealth_reveal_strategy.py",
            "bridges/stealth_order_bridge.py",
        ],
        "resolution_evidence_refs": [
            "stealth_admission_context",
            "active_placement_exchange_truth",
            "mutation_claim_snapshot",
            "lifecycle_write_guard",
        ],
        "resolution_plan_steps": [
            "bind_manager_invocation_to_existing_lifecycle_path",
            "prove_mutation_lock_policy",
            "prove_exchange_reality_invariant_policy",
        ],
        "resolution_dependency_refs": [
            "stealth_manager_invocation_policy",
            "mutation_lock_policy",
            "exchange_reality_invariant_policy",
        ],
        "resolution_verification_gates": [
            "manager_invocation_requires_live_service_and_adapter",
            "mutation_claims_are_respected",
            "revealed_state_matches_exchange_reality",
        ],
        "resolution_handoff_categories": [
            AdminApiLivePreflightCategory.MANAGER_INVOCATION,
            AdminApiLivePreflightCategory.MUTATION_CLAIM,
            AdminApiLivePreflightCategory.LIFECYCLE_WRITE_GUARD,
        ],
        "detail": (
            "Stealth manager invocation must be allowed only through the "
            "existing lifecycle path and mutation locks."
        ),
    },
    AdminApiStealthLiveReadinessDecision.COINBASE_EXCHANGE_SUBMISSION_POLICY: {
        "owner": "exchange_integration",
        "required_artifact": "coinbase_exchange_submission_policy",
        "missing_reason": "coinbase_exchange_submission_policy_missing",
        "resolution_artifacts": [
            "coinbase_exchange_submission_policy",
            "coinbase_cancel_policy",
            "live_coinbase_read_policy",
            "live_cap_evidence",
        ],
        "resolution_contract_refs": [
            "docs/LIVE_ORDER_SURFACES.md",
            "application/admin_api/live_execution.py",
            "integration/coinbase_client.py",
        ],
        "resolution_evidence_refs": [
            "active_placement_exchange_truth",
            "coinbase_exchange",
            "live_execution_adapter_contract",
        ],
        "resolution_plan_steps": [
            "define_coinbase_submit_cancel_read_policy",
            "bind_submission_to_live_adapter",
            "prove_cap_and_exchange_truth_evidence",
        ],
        "resolution_dependency_refs": [
            "coinbase_exchange_submission_policy",
            "coinbase_cancel_policy",
            "live_coinbase_read_policy",
            "live_cap_evidence",
        ],
        "resolution_verification_gates": [
            "coinbase_submit_requires_backend_adapter",
            "coinbase_cancel_uses_client_order_id_wrapper",
            "live_coinbase_read_is_backend_owned_and_audited",
        ],
        "resolution_handoff_categories": [
            AdminApiLivePreflightCategory.COINBASE_EXCHANGE,
        ],
        "detail": (
            "Coinbase submit, cancel, and read behavior must be governed by "
            "backend exchange integration policy and exchange-truth evidence."
        ),
    },
    AdminApiStealthLiveReadinessDecision.POST_WRITE_RECONCILIATION_EXECUTION_POLICY: {
        "owner": "fill_audit",
        "required_artifact": "post_write_reconciliation_execution_policy",
        "missing_reason": "post_write_reconciliation_execution_policy_missing",
        "resolution_artifacts": [
            "post_write_reconciliation_execution_policy",
            "route_bound_reconciliation_plan",
            "accepted_execution_journal",
            "verified_post_write_reconciliation",
        ],
        "resolution_contract_refs": [
            "POST /api/v1/admin/reconciliation/plans",
            "POST /api/v1/stealth/orders/{stealth_order_id}/post-write-reconciliation-proofs",
            "POST /api/v1/stealth/orders/{stealth_order_id}/post-write-execution-journals",
            "POST /api/v1/stealth/orders/{stealth_order_id}/post-write-reconciliation-verifications",
        ],
        "resolution_evidence_refs": [
            "post_write_reconciliation_boundary",
            "post_write_reconciliation_proof",
            "post_write_execution_journal",
            "post_write_reconciliation_verification",
        ],
        "resolution_plan_steps": [
            "require_route_bound_reconciliation_plan",
            "accept_execution_journal_for_exact_context",
            "verify_post_write_reconciliation_before_completion",
        ],
        "resolution_dependency_refs": [
            "route_bound_reconciliation_plan",
            "accepted_execution_journal",
            "verified_post_write_reconciliation",
        ],
        "resolution_verification_gates": [
            "proof_journal_and_verification_match_same_context",
            "reconciliation_execution_is_backend_owned",
            "state_mutation_waits_for_post_write_completion",
        ],
        "resolution_handoff_categories": [
            AdminApiLivePreflightCategory.RECONCILIATION,
        ],
        "detail": (
            "Post-write reconciliation execution policy must exist before "
            "accepted journals or proofs can transition into execution."
        ),
    },
    AdminApiStealthLiveReadinessDecision.STATE_MUTATION_POLICY: {
        "owner": "stealth_lifecycle",
        "required_artifact": "stealth_state_mutation_policy",
        "missing_reason": "state_mutation_policy_missing",
        "resolution_artifacts": [
            "stealth_state_mutation_policy",
            "lifecycle_write_guard",
            "active_placement_exchange_truth",
            "post_write_reconciliation_completion",
        ],
        "resolution_contract_refs": [
            "POST /api/v1/stealth/orders/{stealth_order_id}/lifecycle-write-guard-proofs",
            "POST /api/v1/stealth/orders/{stealth_order_id}/active-placement/exchange-truth-proofs",
            "core/stealth_order_manager.py",
            "database/order.py",
        ],
        "resolution_evidence_refs": [
            "stealth_lifecycle_execution_contract",
            "stealth_command_execution_contract",
            "post_write_completion_verifier",
        ],
        "resolution_plan_steps": [
            "prove_lifecycle_write_guard",
            "prove_active_placement_exchange_truth",
            "prove_post_write_reconciliation_completion",
        ],
        "resolution_dependency_refs": [
            "stealth_state_mutation_policy",
            "lifecycle_write_guard",
            "active_placement_exchange_truth",
            "post_write_reconciliation_completion",
        ],
        "resolution_verification_gates": [
            "state_mutation_requires_live_exchange_handling",
            "order_and_exchange_state_mutation_are_audited",
            "post_write_completion_precedes_local_state_change",
        ],
        "resolution_handoff_categories": [
            AdminApiLivePreflightCategory.STATE_MUTATION,
            AdminApiLivePreflightCategory.LIFECYCLE_WRITE_GUARD,
            AdminApiLivePreflightCategory.COINBASE_EXCHANGE,
            AdminApiLivePreflightCategory.RECONCILIATION,
        ],
        "detail": (
            "Lifecycle, order, and exchange-state mutation policy must preserve "
            "stealth exchange-reality invariants before state can change."
        ),
    },
}

_CLEARANCE_ACTION_CONTRACTS: dict[
    AdminApiLivePreflightCategory, dict[str, str | None]
] = {
    AdminApiLivePreflightCategory.APPROVAL: {
        "required_backend_contract": (
            "POST /api/v1/admin/approvals/requests/{approval_request_id}/decisions"
        ),
        "required_backend_route": (
            "/api/v1/admin/approvals/requests/{approval_request_id}/decisions"
        ),
        "required_backend_method": "POST",
        "required_backend_service": "AdminApprovalService",
        "required_evidence_ref": "route_bound_approval_snapshot",
    },
    AdminApiLivePreflightCategory.AUDIT: {
        "required_backend_contract": "POST /api/v1/admin/admission-audits",
        "required_backend_route": "/api/v1/admin/admission-audits",
        "required_backend_method": "POST",
        "required_backend_service": "AdminAdmissionAuditService",
        "required_evidence_ref": "route_bound_admission_audit",
    },
    AdminApiLivePreflightCategory.CAP_GUARD: {
        "required_backend_contract": "POST /api/v1/admin/cap-guard/decisions",
        "required_backend_route": "/api/v1/admin/cap-guard/decisions",
        "required_backend_method": "POST",
        "required_backend_service": "AdminCapGuardService",
        "required_evidence_ref": "route_bound_cap_guard_decision",
    },
    AdminApiLivePreflightCategory.RECONCILIATION: {
        "required_backend_contract": "POST /api/v1/admin/reconciliation/plans",
        "required_backend_route": "/api/v1/admin/reconciliation/plans",
        "required_backend_method": "POST",
        "required_backend_service": "AdminReconciliationService",
        "required_evidence_ref": "route_bound_reconciliation_plan",
    },
    AdminApiLivePreflightCategory.BROWSER_AUTHORITY: {
        "required_backend_contract": "docs/LIVE_ORDER_SURFACES.md::browser_bff_boundary",
        "required_backend_route": None,
        "required_backend_method": None,
        "required_backend_service": "AdminApiAuthorityBoundaryReview",
        "required_evidence_ref": "browser_bff_authority_rejection",
    },
    AdminApiLivePreflightCategory.LIVE_EXECUTION_SERVICE: {
        "required_backend_contract": (
            "application/admin_api/live_execution.py::AdminApiLiveExecutionService"
        ),
        "required_backend_route": "/api/v1/admin/live-enablement",
        "required_backend_method": "GET",
        "required_backend_service": "AdminApiLiveExecutionService",
        "required_evidence_ref": "live_execution_service_contract",
    },
    AdminApiLivePreflightCategory.LIVE_EXECUTION_ADAPTER: {
        "required_backend_contract": (
            "application/admin_api/live_execution.py::"
            "build_live_execution_adapter_contract"
        ),
        "required_backend_route": None,
        "required_backend_method": None,
        "required_backend_service": "AdminApiCommandService",
        "required_evidence_ref": "live_execution_adapter_contract",
    },
    AdminApiLivePreflightCategory.MANAGER_INVOCATION: {
        "required_backend_contract": "core/stealth_order_manager.py",
        "required_backend_route": None,
        "required_backend_method": None,
        "required_backend_service": "StealthOrderManager",
        "required_evidence_ref": "stealth_manager_invocation_policy",
    },
    AdminApiLivePreflightCategory.MUTATION_CLAIM: {
        "required_backend_contract": (
            "POST /api/v1/stealth/orders/{stealth_order_id}/mutation-claim-proofs"
        ),
        "required_backend_route": (
            "/api/v1/stealth/orders/{stealth_order_id}/mutation-claim-proofs"
        ),
        "required_backend_method": "POST",
        "required_backend_service": "AdminApiCommandService",
        "required_evidence_ref": "mutation_claim_snapshot",
    },
    AdminApiLivePreflightCategory.LIFECYCLE_WRITE_GUARD: {
        "required_backend_contract": (
            "POST /api/v1/stealth/orders/{stealth_order_id}/"
            "lifecycle-write-guard-proofs"
        ),
        "required_backend_route": (
            "/api/v1/stealth/orders/{stealth_order_id}/"
            "lifecycle-write-guard-proofs"
        ),
        "required_backend_method": "POST",
        "required_backend_service": "AdminApiCommandService",
        "required_evidence_ref": "lifecycle_write_guard",
    },
    AdminApiLivePreflightCategory.COINBASE_EXCHANGE: {
        "required_backend_contract": "docs/LIVE_ORDER_SURFACES.md::coinbase_exchange",
        "required_backend_route": None,
        "required_backend_method": None,
        "required_backend_service": "CoinbaseExchangeIntegration",
        "required_evidence_ref": "active_placement_exchange_truth",
    },
    AdminApiLivePreflightCategory.STATE_MUTATION: {
        "required_backend_contract": "core/stealth_order_manager.py::state_mutation_policy",
        "required_backend_route": None,
        "required_backend_method": None,
        "required_backend_service": "StealthOrderManager",
        "required_evidence_ref": "stealth_lifecycle_execution_contract",
    },
}


def build_stealth_execution_preflight(
    candidate: StealthExecutionCandidateEvidence,
) -> StealthExecutionPreflightEvidence:
    """Build read-only preflight evidence for a blocked stealth candidate."""

    checks = [
        _check(
            name="execution_candidate",
            category=AdminApiLivePreflightCategory.EXECUTION_CANDIDATE,
            owner="admin_api_contract",
            evidence=(
                "The backend candidate is present only as blocked planning evidence."
            ),
            detail=(
                "The candidate cannot be executable while execution_allowed=false "
                "or executable=false."
            ),
        ),
        _check(
            name="remaining_blocker_chain",
            category=AdminApiLivePreflightCategory.BLOCKER_CHAIN,
            owner="admin_api_contract",
            evidence=(
                f"{candidate.unresolved_blocker_count} unresolved execution "
                "blockers remain bound to this candidate."
            ),
            detail=(
                "Every unresolved blocker must resolve through backend-owned "
                "contracts before the candidate can move toward execution."
            ),
        ),
        _check(
            name="live_execution_service",
            category=AdminApiLivePreflightCategory.LIVE_EXECUTION_SERVICE,
            owner="admin_api_contract",
            evidence="The shared backend live execution service remains disabled.",
            detail=(
                "No manager, Coinbase, or reconciliation path may run while "
                "the live execution service is disabled."
            ),
        ),
        _check(
            name="live_execution_adapter",
            category=AdminApiLivePreflightCategory.LIVE_EXECUTION_ADAPTER,
            owner="admin_api_contract",
            evidence="No executable live adapter is available for this candidate.",
            detail=(
                "The candidate maps to backend metadata only; it does not "
                "construct or invoke an adapter."
            ),
        ),
        _check(
            name="manager_invocation",
            category=AdminApiLivePreflightCategory.MANAGER_INVOCATION,
            owner="stealth_lifecycle",
            evidence="Stealth manager invocation is disabled for this contract.",
            detail=(
                "Manager methods are named for orientation only and are not "
                "called by preflight or candidate evidence."
            ),
        ),
        _check(
            name="coinbase_exchange",
            category=AdminApiLivePreflightCategory.COINBASE_EXCHANGE,
            owner="exchange_integration",
            evidence="Coinbase submit, cancel, and read actions are disabled.",
            detail=(
                "Candidate-bound preflight must not submit orders, cancel "
                "orders, or read live Coinbase state."
            ),
        ),
        _check(
            name="post_write_reconciliation",
            category=AdminApiLivePreflightCategory.RECONCILIATION,
            owner="admin_api_contract",
            evidence="Reconciliation execution remains disabled.",
            detail=(
                "Post-write reconciliation proof may be displayed, but this "
                "preflight does not execute reconciliation."
            ),
        ),
        _check(
            name="state_mutation",
            category=AdminApiLivePreflightCategory.STATE_MUTATION,
            owner="admin_api_contract",
            evidence="Local lifecycle, order, and exchange-state mutation is disabled.",
            detail=(
                "The preflight contract must not mutate stealth, order, or "
                "exchange-state records."
            ),
        ),
        _check(
            name="browser_bff_authority",
            category=AdminApiLivePreflightCategory.BROWSER_AUTHORITY,
            owner="admin_api_contract",
            evidence="Browser and BFF authority remains display/forward only.",
            detail=(
                "Frontend and BFF layers may display this preflight evidence "
                "but cannot approve or execute the candidate."
            ),
        ),
    ]
    blocking_count = sum(1 for item in checks if item.blocking)
    passed_count = sum(
        1 for item in checks if item.status == AdminApiGateStatus.PASSED
    )
    return StealthExecutionPreflightEvidence(
        mutation_family=candidate.mutation_family,
        workflow_family=candidate.workflow_family,
        command_route=candidate.command_route,
        command_method=candidate.command_method,
        service_method=candidate.service_method,
        identity_value=candidate.identity_value,
        candidate_available=candidate.execution_candidate_available,
        candidate_executable=candidate.executable,
        candidate_execution_allowed=candidate.execution_allowed,
        unresolved_blocker_count=candidate.unresolved_blocker_count,
        unresolved_blockers=list(candidate.unresolved_blockers),
        next_required_contracts=list(candidate.next_required_contracts),
        check_count=len(checks),
        blocking_check_count=blocking_count,
        passed_check_count=passed_count,
        preflight_checks=checks,
        detail=(
            "Candidate-bound preflight is read-only backend evidence. It "
            "keeps the stealth execution candidate blocked until the backend "
            "live service, adapter, manager, Coinbase, reconciliation, and "
            "state-mutation blockers are resolved by later contracts."
        ),
    )


def build_stealth_execution_transition_barrier(
    preflight: StealthExecutionPreflightEvidence,
) -> StealthExecutionTransitionBarrierEvidence:
    """Build the read-only barrier before any execution transition."""

    blocking_checks = [item for item in preflight.preflight_checks if item.blocking]
    first_blocking_check = blocking_checks[0] if blocking_checks else None
    return StealthExecutionTransitionBarrierEvidence(
        mutation_family=preflight.mutation_family,
        workflow_family=preflight.workflow_family,
        command_route=preflight.command_route,
        command_method=preflight.command_method,
        service_method=preflight.service_method,
        identity_key=preflight.identity_key,
        identity_value=preflight.identity_value,
        all_preflight_checks_passed=preflight.blocking_check_count == 0,
        first_blocking_check=(
            first_blocking_check.name if first_blocking_check is not None else None
        ),
        first_blocking_category=(
            first_blocking_check.category
            if first_blocking_check is not None
            else None
        ),
        required_clearance_order=[item.name for item in blocking_checks],
        preflight_check_count=preflight.check_count,
        blocking_check_count=preflight.blocking_check_count,
        passed_check_count=preflight.passed_check_count,
        unresolved_blocker_count=preflight.unresolved_blocker_count,
        unresolved_blockers=list(preflight.unresolved_blockers),
        next_required_contracts=list(preflight.next_required_contracts),
        detail=(
            "Execution transition remains blocked by backend-owned preflight "
            "evidence. The barrier is read-only and cannot invoke managers, "
            "Coinbase, active-placement cancel/replace, reconciliation, or "
            "local state mutation."
        ),
    )


def build_stealth_execution_live_readiness(
    barrier: StealthExecutionTransitionBarrierEvidence,
) -> StealthExecutionLiveReadinessEvidence:
    """Build blocked M55 live-readiness closure from the transition barrier."""

    category_by_blocker = {
        "execution_candidate": AdminApiLivePreflightCategory.EXECUTION_CANDIDATE,
        "remaining_blocker_chain": AdminApiLivePreflightCategory.BLOCKER_CHAIN,
        "live_execution_service": AdminApiLivePreflightCategory.LIVE_EXECUTION_SERVICE,
        "live_execution_adapter": AdminApiLivePreflightCategory.LIVE_EXECUTION_ADAPTER,
        "manager_invocation": AdminApiLivePreflightCategory.MANAGER_INVOCATION,
        "coinbase_exchange": AdminApiLivePreflightCategory.COINBASE_EXCHANGE,
        "post_write_reconciliation": AdminApiLivePreflightCategory.RECONCILIATION,
        "state_mutation": AdminApiLivePreflightCategory.STATE_MUTATION,
        "browser_bff_authority": AdminApiLivePreflightCategory.BROWSER_AUTHORITY,
    }
    handoff_blockers = list(dict.fromkeys(barrier.required_clearance_order))
    handoff_blocker_categories = [
        category_by_blocker[blocker]
        for blocker in handoff_blockers
        if blocker in category_by_blocker
    ]
    backend_decisions = _build_stealth_live_readiness_decisions()
    backend_decision_resolution_summary = (
        _build_backend_decision_resolution_summary(backend_decisions)
    )
    return StealthExecutionLiveReadinessEvidence(
        mutation_family=barrier.mutation_family,
        workflow_family=barrier.workflow_family,
        command_route=barrier.command_route,
        command_method=barrier.command_method,
        service_method=barrier.service_method,
        identity_key=barrier.identity_key,
        identity_value=barrier.identity_value,
        transition_barrier_passed=barrier.all_preflight_checks_passed,
        unresolved_blocker_count=barrier.unresolved_blocker_count,
        unresolved_blockers=list(barrier.unresolved_blockers),
        handoff_blocker_count=len(handoff_blockers),
        handoff_blockers=handoff_blockers,
        handoff_blocker_categories=list(dict.fromkeys(handoff_blocker_categories)),
        required_backend_contracts=list(barrier.next_required_contracts),
        required_backend_decisions=list(_STEALTH_LIVE_READINESS_DECISIONS),
        backend_decision_count=len(backend_decisions),
        backend_decisions=backend_decisions,
        backend_decision_resolution_summary=(
            backend_decision_resolution_summary
        ),
        forbidden_execution_claims=[
            "frontend_approval_as_authority",
            "bff_execution_authority",
            "route_local_executor",
            "manager_invocation_without_live_service",
            "coinbase_order_submit_without_adapter",
            "coinbase_cancel_replace_without_exchange_truth",
            "state_mutation_without_post_write_reconciliation",
        ],
        detail=(
            "M55 stealth command-suite evidence remains blocked after the "
            "transition barrier. This live-readiness closure names the backend "
            "decisions and contracts still required before any future execution "
            "authority can exist; it does not enable live execution."
        ),
    )


def _build_backend_decision_resolution_summary(
    backend_decisions: list[StealthExecutionBackendDecisionEvidence],
) -> StealthExecutionBackendDecisionResolutionSummary:
    blocked_decisions = [
        decision
        for decision in backend_decisions
        if decision.status == AdminApiGateStatus.BLOCKED
        or not decision.resolved
    ]
    clearance_summaries = [
        decision.resolution_handoff.clearance_dependency_summary
        for decision in backend_decisions
    ]
    return StealthExecutionBackendDecisionResolutionSummary(
        total_decision_count=len(backend_decisions),
        required_decision_count=sum(
            1 for decision in backend_decisions if decision.required
        ),
        resolved_decision_count=sum(
            1 for decision in backend_decisions if decision.resolved
        ),
        blocked_decision_count=len(blocked_decisions),
        blocking_decisions=[
            decision.decision for decision in blocked_decisions
        ],
        blocking_owners=list(
            dict.fromkeys(decision.owner for decision in blocked_decisions)
        ),
        blocking_required_artifacts=list(
            dict.fromkeys(
                decision.required_artifact for decision in blocked_decisions
            )
        ),
        blocking_missing_reasons=list(
            dict.fromkeys(
                decision.missing_reason for decision in blocked_decisions
            )
        ),
        first_blocking_decision=(
            blocked_decisions[0].decision if blocked_decisions else None
        ),
        first_blocking_owner=(
            blocked_decisions[0].owner if blocked_decisions else None
        ),
        first_blocking_required_artifact=(
            blocked_decisions[0].required_artifact
            if blocked_decisions
            else None
        ),
        clearance_action_count=sum(
            summary.total_action_count for summary in clearance_summaries
        ),
        blocked_clearance_action_count=sum(
            summary.blocked_action_count for summary in clearance_summaries
        ),
        clearable_action_count=sum(
            len(summary.clearable_action_refs)
            for summary in clearance_summaries
        ),
        terminal_clearance_ref_count=sum(
            len(summary.terminal_action_refs)
            for summary in clearance_summaries
        ),
        detail=(
            "Backend decision resolution summary is backend-derived blocked "
            "evidence over the M55 decision ledger. It aggregates unresolved "
            "decisions, owners, required artifacts, missing reasons, and "
            "clearance action counts without running a resolver, writing a "
            "decision, enabling live execution, invoking managers, "
            "reconciling, mutating state, or calling Coinbase."
        ),
    )


def _build_stealth_live_readiness_decisions() -> list[
    StealthExecutionBackendDecisionEvidence
]:
    decisions = []
    for decision in _STEALTH_LIVE_READINESS_DECISIONS:
        metadata = _STEALTH_LIVE_READINESS_DECISION_METADATA[decision]
        resolution_readiness_items = _build_decision_resolution_readiness_items(
            metadata
        )
        resolution_readiness_summary = (
            _build_decision_resolution_readiness_summary(
                resolution_readiness_items
            )
        )
        decisions.append(
            StealthExecutionBackendDecisionEvidence(
                decision=decision,
                owner=metadata["owner"],
                required_artifact=metadata["required_artifact"],
                missing_reason=metadata["missing_reason"],
                resolution_authority="backend_contract_required",
                resolution_required=True,
                resolution_allowed=False,
                resolution_resolved=False,
                resolution_artifacts=metadata["resolution_artifacts"],
                missing_resolution_artifacts=metadata["resolution_artifacts"],
                resolution_contract_refs=metadata["resolution_contract_refs"],
                resolution_evidence_refs=metadata["resolution_evidence_refs"],
                resolver_allowed=False,
                resolver_ran=False,
                decision_write_allowed=False,
                decision_written=False,
                resolution_plan_required=True,
                resolution_plan_available=True,
                resolution_plan_status=AdminApiGateStatus.BLOCKED,
                resolution_plan_authority="backend_planning_only_no_resolution",
                resolution_plan_steps=metadata["resolution_plan_steps"],
                missing_resolution_plan_steps=metadata["resolution_plan_steps"],
                resolution_dependency_refs=metadata["resolution_dependency_refs"],
                resolution_verification_gates=metadata[
                    "resolution_verification_gates"
                ],
                resolution_readiness_items=resolution_readiness_items,
                resolution_readiness_summary=resolution_readiness_summary,
                resolution_handoff=(
                    _build_decision_resolution_handoff(
                        decision,
                        metadata,
                        resolution_readiness_summary,
                        resolution_readiness_items,
                    )
                ),
                resolution_plan_execution_allowed=False,
                resolution_plan_executed=False,
                detail=metadata["detail"],
            )
        )
    return decisions


def _build_decision_resolution_readiness_items(
    metadata: dict[str, object],
) -> list[StealthExecutionDecisionResolutionReadinessItem]:
    items: list[StealthExecutionDecisionResolutionReadinessItem] = []

    item_specs = [
        (
            AdminApiStealthDecisionResolutionEvidenceType.PLAN_STEP,
            "resolution_plan_steps",
            "resolution_plan_step_missing",
        ),
        (
            AdminApiStealthDecisionResolutionEvidenceType.DEPENDENCY,
            "resolution_dependency_refs",
            "resolution_dependency_missing",
        ),
        (
            AdminApiStealthDecisionResolutionEvidenceType.VERIFICATION_GATE,
            "resolution_verification_gates",
            "resolution_verification_gate_missing",
        ),
    ]
    for item_type, source_ref, missing_reason in item_specs:
        for name in metadata[source_ref]:
            items.append(
                StealthExecutionDecisionResolutionReadinessItem(
                    item_type=item_type,
                    item_name=name,
                    item_order=len(items) + 1,
                    source_ref=source_ref,
                    missing_reason=missing_reason,
                )
            )
    return items


def _build_decision_resolution_readiness_summary(
    items: list[StealthExecutionDecisionResolutionReadinessItem],
) -> StealthExecutionDecisionResolutionReadinessSummary:
    blocked_items = [
        item
        for item in items
        if item.status == AdminApiGateStatus.BLOCKED or not item.resolved
    ]
    return StealthExecutionDecisionResolutionReadinessSummary(
        total_item_count=len(items),
        required_item_count=sum(1 for item in items if item.required),
        resolved_item_count=sum(1 for item in items if item.resolved),
        blocked_item_count=len(blocked_items),
        plan_step_count=sum(
            1
            for item in items
            if item.item_type
            == AdminApiStealthDecisionResolutionEvidenceType.PLAN_STEP
        ),
        dependency_count=sum(
            1
            for item in items
            if item.item_type
            == AdminApiStealthDecisionResolutionEvidenceType.DEPENDENCY
        ),
        verification_gate_count=sum(
            1
            for item in items
            if item.item_type
            == AdminApiStealthDecisionResolutionEvidenceType.VERIFICATION_GATE
        ),
        blocking_item_names=[item.item_name for item in blocked_items],
        missing_reasons=list(
            dict.fromkeys(item.missing_reason for item in blocked_items)
        ),
        first_blocking_item_name=(
            blocked_items[0].item_name if blocked_items else None
        ),
    )


def _build_decision_resolution_handoff(
    decision: AdminApiStealthLiveReadinessDecision,
    metadata: dict[str, object],
    summary: StealthExecutionDecisionResolutionReadinessSummary,
    readiness_items: list[StealthExecutionDecisionResolutionReadinessItem],
) -> StealthExecutionDecisionResolutionHandoff:
    clearance_categories = list(metadata["resolution_handoff_categories"])
    blocked_clearance_refs = list(summary.blocking_item_names)
    clearance_actions = _build_decision_resolution_clearance_actions(
        decision=decision,
        metadata=metadata,
        clearance_categories=clearance_categories,
        blocked_clearance_refs=blocked_clearance_refs,
        readiness_items=readiness_items,
    )
    return StealthExecutionDecisionResolutionHandoff(
        decision=decision,
        owner=str(metadata["owner"]),
        required_artifact=str(metadata["required_artifact"]),
        clearance_categories=clearance_categories,
        blocked_clearance_refs=blocked_clearance_refs,
        clearance_actions=clearance_actions,
        clearance_dependency_summary=(
            _build_decision_resolution_clearance_dependency_summary(
                decision=decision,
                clearance_actions=clearance_actions,
            )
        ),
        first_clearance_category=(
            clearance_categories[0] if clearance_categories else None
        ),
        first_clearance_ref=summary.first_blocking_item_name,
        detail=(
            "Resolution handoff is backend planning evidence derived from the "
            "decision readiness summary. It classifies the blocked clearance "
            "work but does not run a resolver, write a decision, invoke "
            "managers, execute reconciliation, mutate state, or call Coinbase."
        ),
    )


def _build_decision_resolution_clearance_actions(
    *,
    decision: AdminApiStealthLiveReadinessDecision,
    metadata: dict[str, object],
    clearance_categories: list[AdminApiLivePreflightCategory],
    blocked_clearance_refs: list[str],
    readiness_items: list[StealthExecutionDecisionResolutionReadinessItem],
) -> list[StealthExecutionDecisionResolutionClearanceAction]:
    actions: list[StealthExecutionDecisionResolutionClearanceAction] = []
    readiness_item_by_name = {item.item_name: item for item in readiness_items}
    for index, clearance_ref in enumerate(blocked_clearance_refs):
        category = _category_for_resolution_ref(
            clearance_ref=clearance_ref,
            clearance_categories=clearance_categories,
        )
        contract = _CLEARANCE_ACTION_CONTRACTS[category]
        readiness_item = readiness_item_by_name[clearance_ref]
        actions.append(
            StealthExecutionDecisionResolutionClearanceAction(
                decision=decision,
                clearance_category=category,
                clearance_ref=clearance_ref,
                readiness_item_type=readiness_item.item_type,
                readiness_item_order=readiness_item.item_order,
                clearance_sequence=index + 1,
                required_predecessor_refs=blocked_clearance_refs[:index],
                blocking_successor_refs=blocked_clearance_refs[index + 1 :],
                owner=str(metadata["owner"]),
                required_artifact=str(metadata["required_artifact"]),
                required_backend_contract=str(
                    contract["required_backend_contract"]
                ),
                required_backend_route=contract["required_backend_route"],
                required_backend_method=contract["required_backend_method"],
                required_backend_service=contract["required_backend_service"],
                required_evidence_ref=str(contract["required_evidence_ref"]),
                detail=(
                    "Clearance action is backend planning evidence for the "
                    f"{category.value} handoff category and blocked ref "
                    f"{clearance_ref}. It names the backend-owned contract "
                    "required to clear the blocker but does not run a "
                    "resolver, write a decision, execute a manager, mutate "
                    "state, or call Coinbase."
                ),
            )
        )
    return actions


def _build_decision_resolution_clearance_dependency_summary(
    *,
    decision: AdminApiStealthLiveReadinessDecision,
    clearance_actions: list[StealthExecutionDecisionResolutionClearanceAction],
) -> StealthExecutionDecisionResolutionClearanceDependencySummary:
    dependency_blocked_refs = [
        action.clearance_ref
        for action in clearance_actions
        if not action.dependency_ready
    ]
    clearable_action_refs = [
        action.clearance_ref
        for action in clearance_actions
        if action.dependency_ready
        and action.clearance_ready
        and action.resolver_allowed
        and action.decision_write_allowed
        and action.execution_allowed
    ]
    terminal_action_refs = [
        action.clearance_ref
        for action in clearance_actions
        if not action.blocking_successor_refs
    ]
    return StealthExecutionDecisionResolutionClearanceDependencySummary(
        decision=decision,
        total_action_count=len(clearance_actions),
        blocked_action_count=sum(
            1
            for action in clearance_actions
            if action.status == AdminApiGateStatus.BLOCKED
            or not action.clearance_ready
        ),
        ready_action_count=sum(
            1 for action in clearance_actions if action.clearance_ready
        ),
        dependency_ready_count=sum(
            1 for action in clearance_actions if action.dependency_ready
        ),
        dependency_blocked_count=len(dependency_blocked_refs),
        predecessor_edge_count=sum(
            len(action.required_predecessor_refs)
            for action in clearance_actions
        ),
        successor_edge_count=sum(
            len(action.blocking_successor_refs)
            for action in clearance_actions
        ),
        dependency_blocked_refs=dependency_blocked_refs,
        clearable_action_refs=clearable_action_refs,
        terminal_action_refs=terminal_action_refs,
        first_clearance_ref=(
            clearance_actions[0].clearance_ref if clearance_actions else None
        ),
        first_dependency_blocked_ref=(
            dependency_blocked_refs[0] if dependency_blocked_refs else None
        ),
        detail=(
            "Clearance dependency summary is backend-derived blocked "
            "planning evidence over clearance actions. It proves the graph "
            "has no clearable action and does not run a resolver, write a "
            "decision, execute a manager, mutate state, reconcile, or call "
            "Coinbase."
        ),
    )


def _category_for_resolution_ref(
    *,
    clearance_ref: str,
    clearance_categories: list[AdminApiLivePreflightCategory],
) -> AdminApiLivePreflightCategory:
    lowered_ref = clearance_ref.lower()
    candidates: list[AdminApiLivePreflightCategory] = []
    if "approval" in lowered_ref or "operator" in lowered_ref:
        candidates.append(AdminApiLivePreflightCategory.APPROVAL)
    if "admission" in lowered_ref or "audit" in lowered_ref:
        candidates.append(AdminApiLivePreflightCategory.AUDIT)
    if "cap" in lowered_ref or "limit" in lowered_ref:
        candidates.append(AdminApiLivePreflightCategory.CAP_GUARD)
    if "reconciliation" in lowered_ref or "journal" in lowered_ref:
        candidates.append(AdminApiLivePreflightCategory.RECONCILIATION)
    if (
        "browser" in lowered_ref
        or "bff" in lowered_ref
        or "frontend" in lowered_ref
    ):
        candidates.append(AdminApiLivePreflightCategory.BROWSER_AUTHORITY)
    if "service" in lowered_ref or "deployment" in lowered_ref:
        candidates.append(AdminApiLivePreflightCategory.LIVE_EXECUTION_SERVICE)
    if "adapter" in lowered_ref or "command_service" in lowered_ref:
        candidates.append(AdminApiLivePreflightCategory.LIVE_EXECUTION_ADAPTER)
    if "manager" in lowered_ref:
        candidates.append(AdminApiLivePreflightCategory.MANAGER_INVOCATION)
    if "mutation" in lowered_ref:
        candidates.append(AdminApiLivePreflightCategory.MUTATION_CLAIM)
    if "state_mutation" in lowered_ref or "state mutation" in lowered_ref:
        candidates.append(AdminApiLivePreflightCategory.STATE_MUTATION)
    if "lifecycle" in lowered_ref or "write_guard" in lowered_ref:
        candidates.append(AdminApiLivePreflightCategory.LIFECYCLE_WRITE_GUARD)
    if "coinbase" in lowered_ref or "exchange" in lowered_ref:
        candidates.append(AdminApiLivePreflightCategory.COINBASE_EXCHANGE)

    for candidate in candidates:
        if candidate in clearance_categories:
            return candidate
    return clearance_categories[0]


def _check(
    *,
    name: str,
    category: AdminApiLivePreflightCategory,
    owner: str,
    evidence: str,
    detail: str,
) -> AdminLivePreflightCheckItem:
    return AdminLivePreflightCheckItem(
        name=name,
        category=category,
        status=AdminApiGateStatus.BLOCKED,
        required=True,
        blocking=True,
        owner=owner,
        evidence=evidence,
        detail=detail,
    )
