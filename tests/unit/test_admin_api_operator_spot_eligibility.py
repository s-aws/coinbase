"""Pure eight-category operator Spot eligibility coordinator tests."""

from __future__ import annotations

import ast
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
import inspect
from typing import Callable, get_type_hints

import pytest

from application.admin_api.operator_spot_eligibility import (
    APPROVED_SPOT_ELIGIBILITY_ORDER,
    SPOT_ELIGIBILITY_PRODUCT_ID,
    ApprovedSpotEligibilityCategory,
    ApprovedSpotEligibilityReader,
    SpotEligibilityCategoryClaim,
    SpotEligibilityCategoryResult,
    SpotEligibilityCoordinator,
    SpotEligibilityCoordinatorConflict,
    SpotEligibilityCycleClaim,
    SpotEligibilityCycleResult,
    SpotEligibilityLedger,
    SpotEligibilityReadContext,
    SpotEligibilityReadOutcome,
    SpotEligibilityReadResult,
    SpotEligibilityRunContext,
    derive_spot_eligibility_client_order_id,
)


NOW = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)
RUN_ID = "19cae8ee-d8ec-43d3-a0f7-8f55ba1d76a0"
DEFINITION_ID = "2f744264-8d18-46a2-b89d-f0c206216515"
PLAN_SHA256 = "a" * 64
PORTFOLIO_SHA256 = "b" * 64


def _context() -> SpotEligibilityRunContext:
    return SpotEligibilityRunContext(
        run_id=RUN_ID,
        definition_id=DEFINITION_ID,
        definition_revision=3,
        plan_sha256=PLAN_SHA256,
        portfolio_id_sha256=PORTFOLIO_SHA256,
        correlation_id="operator-spot-eligibility-test",
    )


def _success(
    *,
    observed_at: datetime = NOW,
    http_request_count: int = 1,
    evidence_seed: str = "1",
) -> SpotEligibilityReadResult:
    return SpotEligibilityReadResult(
        outcome=SpotEligibilityReadOutcome.SUCCEEDED,
        eligible=True,
        logical_call_count=1,
        http_request_count=http_request_count,
        call_count_exact=True,
        observed_at=observed_at,
        evidence_sha256=evidence_seed * 64,
    )


@dataclass
class _FakeLedger(SpotEligibilityLedger):
    cycle_number: int = 4
    calls: list[tuple[str, object]] = field(default_factory=list)
    finalized: list[SpotEligibilityCategoryResult] = field(default_factory=list)

    def claim_or_resume_cycle(
        self,
        context: SpotEligibilityRunContext,
    ) -> SpotEligibilityCycleClaim:
        self.calls.append(("claim_or_resume_cycle", context))
        return SpotEligibilityCycleClaim(
            cycle_number=self.cycle_number,
            client_order_id=derive_spot_eligibility_client_order_id(
                run_id=context.run_id,
                plan_sha256=context.plan_sha256,
            ),
            started_at=NOW,
        )

    def claim_category(
        self,
        context: SpotEligibilityRunContext,
        category: ApprovedSpotEligibilityCategory,
    ) -> SpotEligibilityCategoryClaim:
        self.calls.append(("claim_category", category))
        return SpotEligibilityCategoryClaim(
            cycle_number=self.cycle_number,
            category=category,
            claimed_at=NOW,
        )

    def finalize_category(
        self,
        context: SpotEligibilityRunContext,
        claim: SpotEligibilityCategoryClaim,
        result: SpotEligibilityCategoryResult,
    ) -> None:
        self.calls.append(("finalize_category", result.category))
        assert claim.cycle_number == self.cycle_number
        assert claim.category is result.category
        self.finalized.append(result)


@dataclass
class _FakeReader(ApprovedSpotEligibilityReader):
    results: dict[
        ApprovedSpotEligibilityCategory,
        SpotEligibilityReadResult | BaseException,
    ] = field(default_factory=dict)
    calls: list[tuple[ApprovedSpotEligibilityCategory, object]] = field(
        default_factory=list
    )

    def _read(self, category, context):
        self.calls.append((category, context))
        result = self.results.get(category, _success())
        if isinstance(result, BaseException):
            raise result
        return result

    def read_api_key_permissions(self, context):
        return self._read(
            ApprovedSpotEligibilityCategory.API_KEY_PERMISSIONS,
            context,
        )

    def read_portfolio_catalog(self, context):
        return self._read(
            ApprovedSpotEligibilityCategory.PORTFOLIO_CATALOG,
            context,
        )

    def read_account_wallet_balances(self, context):
        return self._read(
            ApprovedSpotEligibilityCategory.ACCOUNT_WALLET_BALANCES,
            context,
        )

    def read_product_metadata(self, context):
        return self._read(
            ApprovedSpotEligibilityCategory.PRODUCT_METADATA,
            context,
        )

    def read_best_bid_ask(self, context):
        return self._read(
            ApprovedSpotEligibilityCategory.BEST_BID_ASK,
            context,
        )

    def read_fee_summary(self, context):
        return self._read(
            ApprovedSpotEligibilityCategory.FEE_SUMMARY,
            context,
        )

    def read_exact_order_reconciliation(self, context):
        return self._read(
            ApprovedSpotEligibilityCategory.EXACT_ORDER_RECONCILIATION,
            context,
        )

    def read_account_active_spot_order_catalog(self, context):
        return self._read(
            ApprovedSpotEligibilityCategory.ACCOUNT_ACTIVE_SPOT_ORDER_CATALOG,
            context,
        )


def _coordinator(
    ledger: _FakeLedger,
    reader: _FakeReader,
    *,
    now_factory: Callable[[], datetime] = lambda: NOW,
) -> SpotEligibilityCoordinator:
    return SpotEligibilityCoordinator(
        ledger=ledger,
        reader=reader,
        now_factory=now_factory,
    )


def test_reader_protocol_is_exactly_the_eight_approved_typed_methods():
    read_methods = {
        name
        for name, value in ApprovedSpotEligibilityReader.__dict__.items()
        if not name.startswith("_") and callable(value)
    }
    assert read_methods == {
        "read_api_key_permissions",
        "read_portfolio_catalog",
        "read_account_wallet_balances",
        "read_product_metadata",
        "read_best_bid_ask",
        "read_fee_summary",
        "read_exact_order_reconciliation",
        "read_account_active_spot_order_catalog",
    }
    assert tuple(category.value for category in APPROVED_SPOT_ELIGIBILITY_ORDER) == (
        "API_KEY_PERMISSIONS",
        "PORTFOLIO_CATALOG",
        "ACCOUNT_WALLET_BALANCES",
        "PRODUCT_METADATA",
        "BEST_BID_ASK",
        "FEE_SUMMARY",
        "EXACT_ORDER_RECONCILIATION",
        "ACCOUNT_ACTIVE_SPOT_ORDER_CATALOG",
    )
    for method_name in read_methods:
        assert tuple(
            inspect.signature(
                getattr(ApprovedSpotEligibilityReader, method_name)
            ).parameters
        ) == ("self", "context")
        assert get_type_hints(
            getattr(ApprovedSpotEligibilityReader, method_name)
        ) == {
            "context": SpotEligibilityReadContext,
            "return": SpotEligibilityReadResult,
        }


def test_ledger_protocol_has_only_the_three_cycle_owned_methods():
    ledger_methods = {
        name
        for name, value in SpotEligibilityLedger.__dict__.items()
        if not name.startswith("_") and callable(value)
    }
    assert ledger_methods == {
        "claim_or_resume_cycle",
        "claim_category",
        "finalize_category",
    }
    assert tuple(
        inspect.signature(
            SpotEligibilityLedger.claim_or_resume_cycle
        ).parameters
    ) == ("self", "context")
    assert tuple(
        inspect.signature(SpotEligibilityLedger.claim_category).parameters
    ) == ("self", "context", "category")
    assert tuple(
        inspect.signature(SpotEligibilityLedger.finalize_category).parameters
    ) == ("self", "context", "claim", "result")


def test_happy_path_claims_reads_and_finalizes_once_in_fixed_order():
    ledger = _FakeLedger()
    reader = _FakeReader(
        results={
            ApprovedSpotEligibilityCategory.ACCOUNT_WALLET_BALANCES: _success(
                http_request_count=3,
                evidence_seed="2",
            ),
            ApprovedSpotEligibilityCategory.EXACT_ORDER_RECONCILIATION: _success(
                http_request_count=2,
                evidence_seed="3",
            ),
            ApprovedSpotEligibilityCategory.ACCOUNT_ACTIVE_SPOT_ORDER_CATALOG: _success(
                http_request_count=3,
                evidence_seed="4",
            ),
        }
    )

    result = _coordinator(ledger, reader).run(_context())

    expected = list(APPROVED_SPOT_ELIGIBILITY_ORDER)
    assert [category for category, _context_value in reader.calls] == expected
    assert [item.category for item in ledger.finalized] == expected
    assert [name for name, _value in ledger.calls] == [
        "claim_or_resume_cycle",
        *[
            event
            for _category in expected
            for event in ("claim_category", "finalize_category")
        ],
    ]
    assert result.cycle_number == 4
    assert result.outcome is SpotEligibilityReadOutcome.SUCCEEDED
    assert result.eligible is True
    assert result.logical_call_count == 8
    assert result.coinbase_api_call_count == 13
    assert result.call_count_exact is True
    assert result.completed_categories == tuple(expected)
    assert result.fresh_until == NOW + timedelta(seconds=30)
    assert result.diagnostic_code == "automation_spot_eligibility_succeeded"


def test_reader_context_uses_fixed_product_and_deterministic_exact_child_identity():
    ledger = _FakeLedger(cycle_number=2)
    reader = _FakeReader()

    first = _coordinator(ledger, reader).run(_context())
    second = _coordinator(_FakeLedger(cycle_number=2), _FakeReader()).run(
        _context()
    )

    assert first.client_order_id == second.client_order_id
    assert first.client_order_id == derive_spot_eligibility_client_order_id(
        run_id=RUN_ID,
        plan_sha256=PLAN_SHA256,
    )
    assert first.client_order_id == "7e2de814-fc5e-5683-9fc6-96e8d0c6ed04"
    for _category, read_context in reader.calls:
        assert read_context.product_id == SPOT_ELIGIBILITY_PRODUCT_ID
        assert read_context.product_id == "BTC-USDC"
        assert read_context.client_order_id == first.client_order_id
        assert read_context.cycle_number == 2
        assert read_context.portfolio_id_sha256 == PORTFOLIO_SHA256


def test_clock_and_both_freshness_windows_are_injected():
    ledger = _FakeLedger()
    reader = _FakeReader()

    result = SpotEligibilityCoordinator(
        ledger=ledger,
        reader=reader,
        now_factory=lambda: NOW + timedelta(seconds=1),
        default_freshness=timedelta(seconds=20),
        best_bid_ask_freshness=timedelta(seconds=5),
        active_order_catalog_freshness=timedelta(seconds=3),
    ).run(_context())

    assert result.outcome is SpotEligibilityReadOutcome.SUCCEEDED
    assert result.fresh_until == NOW + timedelta(seconds=3)


def test_proven_rejection_fails_short_without_later_claims_or_reads():
    rejected_category = ApprovedSpotEligibilityCategory.ACCOUNT_WALLET_BALANCES
    ledger = _FakeLedger()
    reader = _FakeReader(
        results={
            rejected_category: SpotEligibilityReadResult(
                outcome=SpotEligibilityReadOutcome.REJECTED,
                eligible=False,
                logical_call_count=1,
                http_request_count=2,
                call_count_exact=True,
                observed_at=NOW,
            )
        }
    )

    result = _coordinator(ledger, reader).run(_context())

    expected = list(APPROVED_SPOT_ELIGIBILITY_ORDER[:3])
    assert [category for category, _context_value in reader.calls] == expected
    assert [item.category for item in ledger.finalized] == expected
    assert result.outcome is SpotEligibilityReadOutcome.REJECTED
    assert result.eligible is False
    assert result.logical_call_count == 3
    assert result.coinbase_api_call_count == 4
    assert result.call_count_exact is True
    assert result.diagnostic_code.endswith(
        "account_wallet_balances_rejected"
    )


def test_reader_exception_is_sanitized_unknown_finalized_once_and_never_retried():
    secret = "withheld-private-account-value"
    failed_category = ApprovedSpotEligibilityCategory.PORTFOLIO_CATALOG
    ledger = _FakeLedger()
    reader = _FakeReader(results={failed_category: RuntimeError(secret)})

    result = _coordinator(ledger, reader).run(_context())

    assert [category for category, _context_value in reader.calls] == list(
        APPROVED_SPOT_ELIGIBILITY_ORDER[:2]
    )
    assert reader.calls.count((failed_category, reader.calls[-1][1])) == 1
    terminal = ledger.finalized[-1]
    assert terminal.category is failed_category
    assert terminal.outcome is SpotEligibilityReadOutcome.UNKNOWN
    assert terminal.eligible is False
    assert terminal.logical_call_count == 1
    assert terminal.http_request_count is None
    assert terminal.call_count_exact is False
    assert secret not in terminal.diagnostic_code
    assert secret not in repr(terminal)
    assert result.coinbase_api_call_count is None
    assert result.call_count_exact is False
    assert result.diagnostic_code == (
        "automation_spot_eligibility_portfolio_catalog_unknown"
    )


def test_stale_success_is_finalized_as_fixed_rejection_without_retry():
    stale_category = ApprovedSpotEligibilityCategory.API_KEY_PERMISSIONS
    ledger = _FakeLedger()
    reader = _FakeReader(
        results={
            stale_category: _success(
                observed_at=NOW - timedelta(seconds=61),
            )
        }
    )

    result = _coordinator(ledger, reader).run(_context())

    assert len(reader.calls) == 1
    terminal = ledger.finalized[-1]
    assert terminal.outcome is SpotEligibilityReadOutcome.REJECTED
    assert terminal.eligible is False
    assert terminal.http_request_count == 1
    assert terminal.call_count_exact is True
    assert terminal.fresh_until == NOW - timedelta(seconds=1)
    assert terminal.diagnostic_code == (
        "automation_spot_eligibility_api_key_permissions_stale"
    )
    assert result.outcome is SpotEligibilityReadOutcome.REJECTED


def test_future_observation_is_rejected_with_fixed_diagnostic():
    ledger = _FakeLedger()
    reader = _FakeReader(
        results={
            ApprovedSpotEligibilityCategory.API_KEY_PERMISSIONS: _success(
                observed_at=NOW + timedelta(microseconds=1),
            )
        }
    )

    result = _coordinator(ledger, reader).run(_context())

    assert result.diagnostic_code == (
        "automation_spot_eligibility_api_key_permissions_future"
    )
    assert result.eligible is False
    assert len(reader.calls) == 1


def test_extreme_future_observation_cannot_escape_sanitized_finalization():
    ledger = _FakeLedger()
    reader = _FakeReader(
        results={
            ApprovedSpotEligibilityCategory.API_KEY_PERMISSIONS: _success(
                observed_at=datetime.max.replace(tzinfo=timezone.utc),
            )
        }
    )

    result = _coordinator(ledger, reader).run(_context())

    assert result.outcome is SpotEligibilityReadOutcome.REJECTED
    assert result.diagnostic_code == (
        "automation_spot_eligibility_api_key_permissions_future"
    )
    assert len(ledger.finalized) == 1


def test_claim_cycle_mismatch_is_fail_closed_before_any_reader_call():
    class _MismatchedLedger(_FakeLedger):
        def claim_category(self, context, category):
            claim = super().claim_category(context, category)
            return replace(claim, cycle_number=claim.cycle_number + 1)

    ledger = _MismatchedLedger()
    reader = _FakeReader()

    with pytest.raises(ValueError, match="spot_eligibility_cycle_claim_mismatch"):
        _coordinator(ledger, reader).run(_context())

    assert reader.calls == []
    assert ledger.finalized == []


def test_different_canonical_child_identity_fails_before_category_or_read():
    class _WrongChildLedger(_FakeLedger):
        def claim_or_resume_cycle(self, context):
            claim = super().claim_or_resume_cycle(context)
            return replace(
                claim,
                client_order_id="00000000-0000-0000-0000-000000000001",
            )

    ledger = _WrongChildLedger()
    reader = _FakeReader()

    with pytest.raises(ValueError, match="spot_eligibility_cycle_claim_mismatch"):
        _coordinator(ledger, reader).run(_context())

    assert [name for name, _value in ledger.calls] == [
        "claim_or_resume_cycle"
    ]
    assert reader.calls == []
    assert ledger.finalized == []


def test_terminal_cycle_replay_returns_stored_result_without_category_or_reader_calls():
    terminal_result = SpotEligibilityCycleResult(
        cycle_number=4,
        outcome=SpotEligibilityReadOutcome.REJECTED,
        eligible=False,
        attempted_categories=(
            ApprovedSpotEligibilityCategory.API_KEY_PERMISSIONS,
        ),
        completed_categories=(),
        logical_call_count=1,
        coinbase_api_call_count=1,
        call_count_exact=True,
        fresh_until=NOW + timedelta(seconds=60),
        client_order_id=derive_spot_eligibility_client_order_id(
            run_id=RUN_ID,
            plan_sha256=PLAN_SHA256,
        ),
        diagnostic_code=(
            "automation_spot_eligibility_api_key_permissions_rejected"
        ),
    )

    class _ReplayLedger(_FakeLedger):
        def claim_or_resume_cycle(self, context):
            self.calls.append(("claim_or_resume_cycle", context))
            return SpotEligibilityCycleClaim(
                cycle_number=4,
                client_order_id=terminal_result.client_order_id,
                started_at=NOW,
                replayed=True,
                terminal_result=terminal_result,
            )

    ledger = _ReplayLedger()
    reader = _FakeReader()

    result = _coordinator(ledger, reader).run(_context())

    assert result == replace(terminal_result, replayed=True)
    assert [name for name, _value in ledger.calls] == [
        "claim_or_resume_cycle"
    ]
    assert reader.calls == []


def test_terminal_cycle_replay_does_not_construct_the_reader():
    terminal_result = SpotEligibilityCycleResult(
        cycle_number=4,
        outcome=SpotEligibilityReadOutcome.UNKNOWN,
        eligible=False,
        attempted_categories=(),
        completed_categories=(),
        logical_call_count=0,
        coinbase_api_call_count=None,
        call_count_exact=False,
        fresh_until=None,
        client_order_id=derive_spot_eligibility_client_order_id(
            run_id=RUN_ID,
            plan_sha256=PLAN_SHA256,
        ),
        diagnostic_code="automation_spot_eligibility_cycle_unknown",
    )

    class _ReplayLedger(_FakeLedger):
        def claim_or_resume_cycle(self, context):
            return SpotEligibilityCycleClaim(
                cycle_number=4,
                client_order_id=terminal_result.client_order_id,
                started_at=NOW,
                replayed=True,
                terminal_result=terminal_result,
            )

    factory_calls = 0

    def unavailable_reader_factory():
        nonlocal factory_calls
        factory_calls += 1
        raise RuntimeError("withheld-reader-configuration")

    result = SpotEligibilityCoordinator(
        ledger=_ReplayLedger(),
        reader_factory=unavailable_reader_factory,
        now_factory=lambda: NOW,
    ).run(_context())

    assert result.replayed is True
    assert result.outcome is SpotEligibilityReadOutcome.UNKNOWN
    assert factory_calls == 0


def test_new_cycle_reader_factory_failure_is_exact_zero_rejection():
    secret = "withheld-reader-configuration"
    ledger = _FakeLedger()

    def unavailable_reader_factory():
        raise RuntimeError(secret)

    result = SpotEligibilityCoordinator(
        ledger=ledger,
        reader_factory=unavailable_reader_factory,
        now_factory=lambda: NOW,
    ).run(_context())

    assert result.outcome is SpotEligibilityReadOutcome.REJECTED
    assert result.coinbase_api_call_count == 0
    assert result.call_count_exact is True
    assert result.attempted_categories == (
        ApprovedSpotEligibilityCategory.API_KEY_PERMISSIONS,
    )
    assert result.completed_categories == ()
    assert ledger.finalized[-1].diagnostic_code == (
        "automation_spot_eligibility_api_key_permissions_rejected"
    )
    assert secret not in repr(result)


def test_open_cycle_replay_fails_closed_without_category_or_reader_calls():
    class _OpenReplayLedger(_FakeLedger):
        def claim_or_resume_cycle(self, context):
            self.calls.append(("claim_or_resume_cycle", context))
            return SpotEligibilityCycleClaim(
                cycle_number=4,
                client_order_id=derive_spot_eligibility_client_order_id(
                    run_id=context.run_id,
                    plan_sha256=context.plan_sha256,
                ),
                started_at=NOW,
                replayed=True,
            )

    ledger = _OpenReplayLedger()
    reader = _FakeReader()

    with pytest.raises(SpotEligibilityCoordinatorConflict) as exc_info:
        _coordinator(ledger, reader).run(_context())

    assert exc_info.value.code == (
        "automation_spot_eligibility_cycle_in_progress"
    )
    assert [name for name, _value in ledger.calls] == [
        "claim_or_resume_cycle"
    ]
    assert reader.calls == []


@pytest.mark.parametrize(
    "completed",
    [(), APPROVED_SPOT_ELIGIBILITY_ORDER[:1]],
)
def test_recovered_unknown_cycle_replay_never_reinvokes_reads(completed):
    terminal_result = SpotEligibilityCycleResult(
        cycle_number=4,
        outcome=SpotEligibilityReadOutcome.UNKNOWN,
        eligible=False,
        attempted_categories=completed,
        completed_categories=completed,
        logical_call_count=len(completed),
        coinbase_api_call_count=None,
        call_count_exact=False,
        fresh_until=None,
        client_order_id=derive_spot_eligibility_client_order_id(
            run_id=RUN_ID,
            plan_sha256=PLAN_SHA256,
        ),
        diagnostic_code="automation_spot_eligibility_cycle_unknown",
    )

    class _RecoveredReplayLedger(_FakeLedger):
        def claim_or_resume_cycle(self, context):
            self.calls.append(("claim_or_resume_cycle", context))
            return SpotEligibilityCycleClaim(
                cycle_number=4,
                client_order_id=terminal_result.client_order_id,
                started_at=NOW,
                replayed=True,
                terminal_result=terminal_result,
            )

    ledger = _RecoveredReplayLedger()
    reader = _FakeReader()

    result = _coordinator(ledger, reader).run(_context())

    assert result == replace(terminal_result, replayed=True)
    assert [name for name, _value in ledger.calls] == [
        "claim_or_resume_cycle"
    ]
    assert reader.calls == []


@pytest.mark.parametrize(
    "kwargs",
    [
        {
            "outcome": SpotEligibilityReadOutcome.SUCCEEDED,
            "eligible": False,
            "logical_call_count": 1,
            "http_request_count": 1,
            "call_count_exact": True,
            "observed_at": NOW,
            "evidence_sha256": "c" * 64,
        },
        {
            "outcome": SpotEligibilityReadOutcome.UNKNOWN,
            "eligible": False,
            "logical_call_count": 1,
            "http_request_count": 1,
            "call_count_exact": False,
            "observed_at": NOW,
        },
        {
            "outcome": SpotEligibilityReadOutcome.REJECTED,
            "eligible": False,
            "logical_call_count": 1,
            "http_request_count": None,
            "call_count_exact": True,
            "observed_at": NOW,
        },
    ],
)
def test_read_result_rejects_incoherent_accounting(kwargs):
    with pytest.raises(ValueError):
        SpotEligibilityReadResult(**kwargs)


@pytest.mark.parametrize(
    ("outcome", "call_count", "count_exact", "fresh_until"),
    [
        (SpotEligibilityReadOutcome.UNKNOWN, 1, True, None),
        (
            SpotEligibilityReadOutcome.UNKNOWN,
            None,
            False,
            NOW + timedelta(seconds=1),
        ),
        (SpotEligibilityReadOutcome.REJECTED, None, False, None),
    ],
)
def test_cycle_result_rejects_incoherent_terminal_accounting(
    outcome,
    call_count,
    count_exact,
    fresh_until,
):
    with pytest.raises(ValueError):
        SpotEligibilityCycleResult(
            cycle_number=4,
            outcome=outcome,
            eligible=False,
            attempted_categories=(
                ApprovedSpotEligibilityCategory.API_KEY_PERMISSIONS,
            ),
            completed_categories=(),
            logical_call_count=1,
            coinbase_api_call_count=call_count,
            call_count_exact=count_exact,
            fresh_until=fresh_until,
            client_order_id=derive_spot_eligibility_client_order_id(
                run_id=RUN_ID,
                plan_sha256=PLAN_SHA256,
            ),
            diagnostic_code="automation_spot_eligibility_cycle_unknown",
        )


@pytest.mark.parametrize(
    ("outcome", "attempted", "completed", "call_count", "diagnostic"),
    [
        (
            SpotEligibilityReadOutcome.SUCCEEDED,
            APPROVED_SPOT_ELIGIBILITY_ORDER,
            APPROVED_SPOT_ELIGIBILITY_ORDER,
            6,
            "automation_spot_eligibility_succeeded",
        ),
        (
            SpotEligibilityReadOutcome.REJECTED,
            APPROVED_SPOT_ELIGIBILITY_ORDER[:2],
            APPROVED_SPOT_ELIGIBILITY_ORDER[:1],
            0,
            "automation_spot_eligibility_portfolio_catalog_rejected",
        ),
    ],
)
def test_cycle_result_cannot_understate_completed_read_requests(
    outcome,
    attempted,
    completed,
    call_count,
    diagnostic,
):
    with pytest.raises(ValueError):
        SpotEligibilityCycleResult(
            cycle_number=4,
            outcome=outcome,
            eligible=outcome is SpotEligibilityReadOutcome.SUCCEEDED,
            attempted_categories=attempted,
            completed_categories=completed,
            logical_call_count=len(attempted),
            coinbase_api_call_count=call_count,
            call_count_exact=True,
            fresh_until=NOW + timedelta(seconds=1),
            client_order_id=derive_spot_eligibility_client_order_id(
                run_id=RUN_ID,
                plan_sha256=PLAN_SHA256,
            ),
            diagnostic_code=diagnostic,
        )


def test_result_models_reject_arbitrary_sanitized_looking_diagnostics():
    with pytest.raises(ValueError):
        SpotEligibilityCategoryResult(
            category=ApprovedSpotEligibilityCategory.API_KEY_PERMISSIONS,
            outcome=SpotEligibilityReadOutcome.UNKNOWN,
            eligible=False,
            logical_call_count=1,
            http_request_count=None,
            call_count_exact=False,
            observed_at=NOW,
            fresh_until=None,
            evidence_sha256=None,
            diagnostic_code="unexpected_internal_detail",
        )

    with pytest.raises(ValueError):
        SpotEligibilityCycleResult(
            cycle_number=4,
            outcome=SpotEligibilityReadOutcome.UNKNOWN,
            eligible=False,
            attempted_categories=(),
            completed_categories=(),
            logical_call_count=0,
            coinbase_api_call_count=None,
            call_count_exact=False,
            fresh_until=None,
            client_order_id=derive_spot_eligibility_client_order_id(
                run_id=RUN_ID,
                plan_sha256=PLAN_SHA256,
            ),
            diagnostic_code="unexpected_internal_detail",
        )


def test_module_has_no_active_catalog_or_execution_capability_symbols():
    import application.admin_api.operator_spot_eligibility as module

    source = inspect.getsource(module)
    tree = ast.parse(source)
    forbidden_identifiers = {
        "COINBASE_ACTIVE_SPOT_ORDER_QUERY",
        "canonical_coinbase_execution_scope",
        "AdminApiCommandService",
        "create_order",
        "cancel_order",
        "cancel_orders",
        "order_status",
    }
    observed_names = {
        node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
    }
    observed_attributes = {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }
    observed_arguments = {
        argument.arg
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        for argument in (*node.args.args, *node.args.kwonlyargs)
    }
    observed_strings = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    observed_imports = {
        imported
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
        for imported in (alias.name, alias.asname)
        if imported is not None
    }
    observed_import_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }

    assert forbidden_identifiers.isdisjoint(observed_names)
    assert forbidden_identifiers.isdisjoint(observed_attributes)
    assert forbidden_identifiers.isdisjoint(observed_arguments)
    assert forbidden_identifiers.isdisjoint(observed_imports)
    assert forbidden_identifiers.isdisjoint(observed_import_modules)
    assert not any(
        forbidden in value
        for forbidden in forbidden_identifiers
        for value in observed_strings
    )
    assert not any(forbidden in source for forbidden in forbidden_identifiers)
    assert "mvp_service" not in source
    assert "_read_account_reality_categories" not in source
