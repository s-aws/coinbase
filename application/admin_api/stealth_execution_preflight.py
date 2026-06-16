"""Candidate-bound pre-execution evidence for stealth command contracts."""

from __future__ import annotations

from core.enums import (
    AdminApiGateStatus,
    AdminApiLivePreflightCategory,
)

from .models import (
    AdminLivePreflightCheckItem,
    StealthExecutionCandidateEvidence,
    StealthExecutionPreflightEvidence,
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
