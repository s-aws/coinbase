"""PostgreSQL adaptation for one bounded Spot eligibility cycle."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

import pytest

from application.admin_api.automation_models import AutomationMutationContext
from application.admin_api.operator_spot_eligibility import (
    APPROVED_SPOT_ELIGIBILITY_ORDER,
    SPOT_ELIGIBILITY_DOCUMENTED_MARKET_FRESHNESS_GOAL_KEY,
    ApprovedSpotEligibilityCategory,
    SpotEligibilityCategoryResult,
    SpotEligibilityCoordinator,
    SpotEligibilityCoordinatorConflict,
    SpotEligibilityReadOutcome,
    SpotEligibilityRunContext,
    derive_spot_eligibility_client_order_id,
)
from application.admin_api.operator_spot_eligibility_postgres import (
    PostgresSpotEligibilityLedger,
)


NOW = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)
RUN_ID = "19cae8ee-d8ec-43d3-a0f7-8f55ba1d76a0"
DEFINITION_ID = "2f744264-8d18-46a2-b89d-f0c206216515"
AUDIT_ID = "26371b41-f16e-4dad-83cc-946055440c62"
PLAN_SHA256 = "a" * 64
PORTFOLIO_SHA256 = "b" * 64


def _run_context() -> SpotEligibilityRunContext:
    return SpotEligibilityRunContext(
        run_id=RUN_ID,
        definition_id=DEFINITION_ID,
        definition_revision=1,
        plan_sha256=PLAN_SHA256,
        portfolio_id_sha256=PORTFOLIO_SHA256,
        correlation_id="eligibility-correlation",
    )


def _mutation_context() -> AutomationMutationContext:
    return AutomationMutationContext(
        actor_id="operator-ledger-test",
        roles=("trader",),
        idempotency_key="eligibility-request-1",
        correlation_id="eligibility-correlation",
        operator_intent="refresh_automation_spot_eligibility",
    )


def _request(*, reason: str = "Refresh this exact source-gated run") -> dict[str, Any]:
    return {
        "confirm_approved_eligibility_reads": True,
        "confirm_account_wide_active_spot_order_catalog_read": True,
        "confirm_unknown_consumes_cycle": True,
        "expected_plan_sha256": PLAN_SHA256,
        "reason": reason,
    }


def _authorization_request() -> dict[str, Any]:
    return {
        "confirm_single_child_create": True,
        "confirm_final_eligibility_refresh": True,
        "confirm_account_wide_active_spot_order_catalog_read": True,
        "confirm_unknown_consumes_allowance": True,
        "expected_plan_sha256": PLAN_SHA256,
        "reason": "Authorize this exact child after a fresh final cycle",
    }


def _preview_authorization_request() -> dict[str, Any]:
    return {
        "confirm_single_preview": True,
        "confirm_conditional_single_child_create": True,
        "confirm_final_eligibility_refresh": True,
        "confirm_account_wide_active_spot_order_catalog_read": True,
        "confirm_preview_unknown_consumes_allowance": True,
        "confirm_create_unknown_consumes_allowance": True,
        "expected_plan_sha256": PLAN_SHA256,
        "reason": "Preview once and conditionally create this exact child",
    }


def _cycle(*, state: str = "OPEN") -> SimpleNamespace:
    client_order_id = derive_spot_eligibility_client_order_id(
        run_id=RUN_ID,
        plan_sha256=PLAN_SHA256,
    )
    return SimpleNamespace(
        goal_key="operator_spot_automation_single_child_execution_adapter_v1",
        cycle_number=1,
        run_id=RUN_ID,
        definition_id=DEFINITION_ID,
        definition_revision=1,
        plan_sha256=PLAN_SHA256,
        portfolio_id_sha256=PORTFOLIO_SHA256,
        product_id="BTC-USDC",
        client_order_id=client_order_id,
        state=state,
        coinbase_api_call_count=(8 if state == "SUCCEEDED" else None),
        call_count_exact=state == "SUCCEEDED",
        fresh_until=(
            (NOW + timedelta(seconds=30)).isoformat()
            if state == "SUCCEEDED"
            else None
        ),
        diagnostic_code=f"automation_spot_eligibility_cycle_{state.lower()}",
        audit_id=AUDIT_ID,
        correlation_id="eligibility-correlation",
        started_at=NOW.isoformat(),
        finalized_at=(NOW.isoformat() if state != "OPEN" else None),
    )


def _attempt(
    category: ApprovedSpotEligibilityCategory,
    *,
    cycle_number: int = 1,
) -> SimpleNamespace:
    return SimpleNamespace(
        run_id=RUN_ID,
        cycle_number=cycle_number,
        category=category.value,
        allowance_consumed=True,
        outcome="SUCCEEDED",
        eligible=True,
        coinbase_api_call_count=1,
        call_count_exact=True,
        observed_at=NOW.isoformat(),
        fresh_until=(NOW + timedelta(seconds=30)).isoformat(),
        evidence_sha256="c" * 64,
        diagnostic_code=(
            f"automation_spot_eligibility_{category.value.lower()}_succeeded"
        ),
        audit_id=AUDIT_ID,
        correlation_id="eligibility-correlation",
        started_at=NOW.isoformat(),
        finalized_at=NOW.isoformat(),
        portfolio_id_sha256=(
            PORTFOLIO_SHA256
            if category is ApprovedSpotEligibilityCategory.PORTFOLIO_CATALOG
            else None
        ),
    )


@dataclass
class _Mutation:
    entity: Any
    audit_id: str = AUDIT_ID
    correlation_id: str = "eligibility-correlation"
    replayed: bool = False


class _RawRepository:
    def __init__(self, *, replayed: bool = False, state: str = "OPEN") -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.replayed = replayed
        self.cycle = _cycle(state=state)
        self.attempts = (
            tuple(_attempt(category) for category in APPROVED_SPOT_ELIGIBILITY_ORDER)
            if state == "SUCCEEDED"
            else ()
        )

    def resume_spot_source_gated_run(self, run_id: str, **kwargs: Any) -> _Mutation:
        self.calls.append(("resume_spot_source_gated_run", {"run_id": run_id, **kwargs}))
        allocation = SimpleNamespace(
            run=SimpleNamespace(run_id=RUN_ID),
            cycle=self.cycle,
        )
        return _Mutation(entity=allocation, replayed=self.replayed)

    def allocate_spot_authorization_cycle(
        self,
        run_id: str,
        **kwargs: Any,
    ) -> _Mutation:
        self.calls.append(
            ("allocate_spot_authorization_cycle", {"run_id": run_id, **kwargs})
        )
        allocation = SimpleNamespace(
            run=SimpleNamespace(run_id=RUN_ID),
            cycle=self.cycle,
        )
        return _Mutation(entity=allocation, replayed=self.replayed)

    def list_spot_eligibility_cycles(self) -> tuple[SimpleNamespace, ...]:
        self.calls.append(("list_spot_eligibility_cycles", {}))
        return (self.cycle,)

    def list_spot_eligibility_attempts(
        self,
        run_id: str,
        *,
        cycle_number: int | None = None,
    ) -> tuple[SimpleNamespace, ...]:
        self.calls.append(
            (
                "list_spot_eligibility_attempts",
                {"run_id": run_id, "cycle_number": cycle_number},
            )
        )
        return tuple(
            attempt
            for attempt in self.attempts
            if cycle_number is None or attempt.cycle_number == cycle_number
        )

    def start_spot_eligibility_attempt(
        self,
        run_id: str,
        **kwargs: Any,
    ) -> _Mutation:
        self.calls.append(
            ("start_spot_eligibility_attempt", {"run_id": run_id, **kwargs})
        )
        category = ApprovedSpotEligibilityCategory(kwargs["category"])
        return _Mutation(
            entity=SimpleNamespace(
                **{
                    **vars(_attempt(category)),
                    "outcome": None,
                    "eligible": None,
                    "coinbase_api_call_count": None,
                    "call_count_exact": False,
                    "observed_at": None,
                    "fresh_until": None,
                    "evidence_sha256": None,
                    "finalized_at": None,
                }
            ),
        )

    def finalize_spot_eligibility_attempt(
        self,
        run_id: str,
        **kwargs: Any,
    ) -> _Mutation:
        self.calls.append(
            ("finalize_spot_eligibility_attempt", {"run_id": run_id, **kwargs})
        )
        category = ApprovedSpotEligibilityCategory(kwargs["category"])
        return _Mutation(
            entity=SimpleNamespace(
                **{
                    **vars(_attempt(category)),
                    "outcome": kwargs["outcome"],
                    "eligible": kwargs["eligible"],
                    "coinbase_api_call_count": kwargs[
                        "coinbase_api_call_count"
                    ],
                    "call_count_exact": kwargs["call_count_exact"],
                    "observed_at": (
                        kwargs["observed_at"].isoformat()
                        if kwargs["observed_at"] is not None
                        else None
                    ),
                    "fresh_until": (
                        kwargs["fresh_until"].isoformat()
                        if kwargs["fresh_until"] is not None
                        else None
                    ),
                    "evidence_sha256": kwargs["evidence_sha256"],
                    "portfolio_id_sha256": kwargs[
                        "portfolio_id_sha256"
                    ],
                }
            )
        )


def test_ledger_allocates_one_cycle_and_maps_one_category_with_fixed_commands():
    raw = _RawRepository()
    ledger = PostgresSpotEligibilityLedger(
        repository=raw,
        mutation_context=_mutation_context(),
        request_payload=_request(),
    )
    context = _run_context()

    cycle = ledger.claim_or_resume_cycle(context)
    category = ApprovedSpotEligibilityCategory.API_KEY_PERMISSIONS
    claim = ledger.claim_category(context, category)
    result = SpotEligibilityCategoryResult(
        category=category,
        outcome=SpotEligibilityReadOutcome.SUCCEEDED,
        eligible=True,
        logical_call_count=1,
        http_request_count=1,
        call_count_exact=True,
        observed_at=NOW,
        fresh_until=NOW + timedelta(seconds=60),
        evidence_sha256="c" * 64,
        diagnostic_code=(
            "automation_spot_eligibility_api_key_permissions_succeeded"
        ),
    )
    ledger.finalize_category(context, claim, result)

    assert cycle.cycle_number == 1
    assert cycle.replayed is False
    assert claim.cycle_number == 1
    assert [name for name, _kwargs in raw.calls] == [
        "resume_spot_source_gated_run",
        "start_spot_eligibility_attempt",
        "finalize_spot_eligibility_attempt",
    ]
    resume = raw.calls[0][1]
    assert resume["expected_plan_sha256"] == PLAN_SHA256
    assert resume["command"].idempotency_key == "eligibility-request-1"
    start = raw.calls[1][1]
    finalize = raw.calls[2][1]
    assert start["category"] == "API_KEY_PERMISSIONS"
    assert start["command"].idempotency_key != resume["command"].idempotency_key
    assert finalize["command"].idempotency_key != start["command"].idempotency_key
    assert finalize["observed_at"] == NOW
    assert finalize["fresh_until"] == NOW + timedelta(seconds=60)
    assert finalize["evidence_sha256"] == "c" * 64
    assert finalize["portfolio_id_sha256"] is None


def test_ledger_persists_v3_missing_market_time_as_null_without_freshness_proxy():
    raw = _RawRepository()
    raw.cycle.goal_key = SPOT_ELIGIBILITY_DOCUMENTED_MARKET_FRESHNESS_GOAL_KEY
    raw.cycle.client_order_id = derive_spot_eligibility_client_order_id(
        run_id=RUN_ID,
        plan_sha256=PLAN_SHA256,
        goal_key=SPOT_ELIGIBILITY_DOCUMENTED_MARKET_FRESHNESS_GOAL_KEY,
    )
    ledger = PostgresSpotEligibilityLedger(
        repository=raw,
        mutation_context=_mutation_context(),
        request_payload=_request(),
    )
    context = replace(
        _run_context(),
        goal_key=SPOT_ELIGIBILITY_DOCUMENTED_MARKET_FRESHNESS_GOAL_KEY,
    )
    ledger.claim_or_resume_cycle(context)
    category = ApprovedSpotEligibilityCategory.BEST_BID_ASK
    claim = ledger.claim_category(context, category)

    ledger.finalize_category(
        context,
        claim,
        SpotEligibilityCategoryResult(
            category=category,
            outcome=SpotEligibilityReadOutcome.REJECTED,
            eligible=False,
            logical_call_count=1,
            http_request_count=1,
            call_count_exact=True,
            observed_at=None,
            fresh_until=None,
            evidence_sha256=None,
            diagnostic_code=(
                "automation_spot_eligibility_best_bid_ask_rejected"
            ),
        ),
    )

    finalize = raw.calls[-1][1]
    assert finalize["coinbase_api_call_count"] == 1
    assert finalize["call_count_exact"] is True
    assert finalize["observed_at"] is None
    assert finalize["fresh_until"] is None
    assert finalize["evidence_sha256"] is None


class _ExplodingReader:
    calls = 0

    def __getattr__(self, _name: str):
        def explode(_context: Any) -> Any:
            self.calls += 1
            raise AssertionError("terminal replay must not invoke a reader")

        return explode


def test_terminal_cycle_replay_reconstructs_result_without_reader_calls():
    raw = _RawRepository(replayed=True, state="SUCCEEDED")
    ledger = PostgresSpotEligibilityLedger(
        repository=raw,
        mutation_context=_mutation_context(),
        request_payload=_request(),
    )
    reader = _ExplodingReader()

    result = SpotEligibilityCoordinator(
        ledger=ledger,
        reader=reader,
        now_factory=lambda: NOW,
    ).run(_run_context())

    assert result.replayed is True
    assert result.eligible is True
    assert result.completed_categories == APPROVED_SPOT_ELIGIBILITY_ORDER
    assert result.coinbase_api_call_count == 8
    assert reader.calls == 0
    assert [name for name, _kwargs in raw.calls] == [
        "resume_spot_source_gated_run",
        "list_spot_eligibility_attempts",
    ]


def test_restart_unknown_cycle_with_zero_attempts_replays_without_reader_calls():
    raw = _RawRepository(replayed=True, state="UNKNOWN")
    ledger = PostgresSpotEligibilityLedger(
        repository=raw,
        mutation_context=_mutation_context(),
        request_payload=_request(),
    )
    reader = _ExplodingReader()

    result = SpotEligibilityCoordinator(
        ledger=ledger,
        reader=reader,
        now_factory=lambda: NOW,
    ).run(_run_context())

    assert result.replayed is True
    assert result.outcome is SpotEligibilityReadOutcome.UNKNOWN
    assert result.attempted_categories == ()
    assert result.coinbase_api_call_count is None
    assert reader.calls == 0


def test_open_cycle_replay_fails_closed_without_reader_calls():
    raw = _RawRepository(replayed=True, state="OPEN")
    ledger = PostgresSpotEligibilityLedger(
        repository=raw,
        mutation_context=_mutation_context(),
        request_payload=_request(),
    )
    reader = _ExplodingReader()

    with pytest.raises(
        SpotEligibilityCoordinatorConflict,
        match="automation_spot_eligibility_cycle_in_progress",
    ):
        SpotEligibilityCoordinator(
            ledger=ledger,
            reader=reader,
            now_factory=lambda: NOW,
        ).run(_run_context())

    assert reader.calls == 0


def test_outer_cycle_payload_hash_binds_the_full_operator_request():
    first_raw = _RawRepository()
    second_raw = _RawRepository()
    PostgresSpotEligibilityLedger(
        repository=first_raw,
        mutation_context=_mutation_context(),
        request_payload=_request(reason="First bounded refresh reason"),
    ).claim_or_resume_cycle(_run_context())
    PostgresSpotEligibilityLedger(
        repository=second_raw,
        mutation_context=_mutation_context(),
        request_payload=_request(reason="Changed bounded refresh reason"),
    ).claim_or_resume_cycle(_run_context())

    first_command = first_raw.calls[0][1]["command"]
    second_command = second_raw.calls[0][1]["command"]
    assert first_command.idempotency_key == second_command.idempotency_key
    assert first_command.payload_sha256 != second_command.payload_sha256


def test_authorization_cycle_uses_a_distinct_typed_repository_transition():
    raw = _RawRepository()
    ledger = PostgresSpotEligibilityLedger(
        repository=raw,
        mutation_context=_mutation_context(),
        request_payload=_authorization_request(),
        authorization_cycle=True,
    )

    claim = ledger.claim_or_resume_cycle(_run_context())

    assert claim.replayed is False
    assert [name for name, _kwargs in raw.calls] == [
        "allocate_spot_authorization_cycle"
    ]
    command = raw.calls[0][1]["command"]
    assert command.idempotency_key == "eligibility-request-1"


def test_preview_authorization_cycle_uses_the_same_typed_final_refresh_boundary():
    raw = _RawRepository()
    ledger = PostgresSpotEligibilityLedger(
        repository=raw,
        mutation_context=_mutation_context(),
        request_payload=_preview_authorization_request(),
        authorization_cycle=True,
    )

    claim = ledger.claim_or_resume_cycle(_run_context())

    assert claim.replayed is False
    assert [name for name, _kwargs in raw.calls] == [
        "allocate_spot_authorization_cycle"
    ]
