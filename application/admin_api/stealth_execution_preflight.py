"""Candidate-bound pre-execution evidence for stealth command contracts."""

from __future__ import annotations

from core.enums import (
    AdminApiGateStatus,
    AdminApiLivePreflightCategory,
)

from .models import (
    AdminLivePreflightCheckItem,
    StealthExecutionCandidateEvidence,
    StealthExecutionLiveReadinessEvidence,
    StealthExecutionPreflightEvidence,
    StealthExecutionTransitionBarrierEvidence,
)


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
        required_backend_decisions=[
            "explicit_live_enablement_decision",
            "backend_live_service_configuration",
            "backend_live_adapter_construction",
            "manager_invocation_policy",
            "coinbase_exchange_submission_policy",
            "post_write_reconciliation_execution_policy",
            "state_mutation_policy",
        ],
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
