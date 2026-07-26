"""PostgreSQL invariants for the bounded Goal 10 Futures lifecycle."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
import re
import uuid

from psycopg2 import sql
import pytest

from application.admin_api.operator_futures_manual_lifecycle import (
    FUTURES_MANUAL_ACTIVE_GOAL_ID,
    FUTURES_MANUAL_ELIGIBILITY_CATEGORIES,
    FUTURES_MANUAL_MARGIN_SUBREADS,
    FuturesManualEligibilityResult,
    FuturesHotpointExternalCommandReadback,
    FuturesManualRequestContext,
)
from application.admin_api.operator_futures_manual_runtime import (
    FuturesManualCancelExecution,
    FuturesManualCreateExecution,
    FuturesManualPreviewExecution,
    FuturesManualReconciliationExecution,
)
from application.admin_api.operator_futures_hotpoint_v2 import (
    FUTURES_HOTPOINT_GOAL_ID,
    FUTURES_HOTPOINT_POLICY_REVISION,
    FUTURES_HOTPOINT_POLICY_SHA256,
    FuturesHotpointReconciliationExecution,
    validate_futures_hotpoint_candidate_execution_window,
    validate_futures_hotpoint_candidate,
    validate_futures_hotpoint_eligibility_evidence,
)
from application.admin_api.operator_hotpoint_control import (
    HOTPOINT_SAFE_CLOSEOUT_OPERATOR_INTENT,
)
from core.enums import (
    AdminFuturesManualCallOutcome,
    AdminFuturesManualEligibilityOutcome,
)
from database.database import PostgresDB
from database.operator_futures_manual_lifecycle import (
    OperatorFuturesManualLifecycleRepository,
)


pytestmark = [pytest.mark.regression, pytest.mark.integration, pytest.mark.serial]

TEST_DB_HOST = "coinbase-test-postgres"
TEST_DB_PORT = 9876
TEST_DB_PASSWORD = os.environ.get("COINBASE_DB_PASSWORD", "postgres")
PORTFOLIO_ID = "11111111-2222-4333-8444-555555555555"
TEST_NOW = datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)
_SCHEMA_RE = re.compile(r"^test_operator_futures_manual_[0-9a-f]{32}$")


def _database() -> PostgresDB:
    return PostgresDB(
        host=TEST_DB_HOST,
        port=TEST_DB_PORT,
        database="postgres",
        user="postgres",
        password=TEST_DB_PASSWORD,
    )


@pytest.fixture
def repository():
    schema = f"test_operator_futures_manual_{uuid.uuid4().hex}"
    assert _SCHEMA_RE.fullmatch(schema)
    admin = _database()
    admin.connect()
    with admin.get_cursor() as cursor:
        cursor.execute(
            sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema))
        )
    repo_db = _database()
    repo = OperatorFuturesManualLifecycleRepository(
        repo_db,
        schema=schema,
        configured_portfolio_id=None,
        clock=lambda: TEST_NOW,
    )
    repo.ensure_schema()
    try:
        yield repo
    finally:
        repo_db.disconnect()
        with admin.get_cursor() as cursor:
            cursor.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(
                    sql.Identifier(schema)
                )
            )
        admin.disconnect()


def _context(*, revision: int, key: str, execute: bool = False):
    return FuturesManualRequestContext(
        actor_id="operator-1",
        roles=("admin", "trader"),
        expected_revision=revision,
        idempotency_key=key,
        correlation_id=f"corr-{key}",
        audit_id=str(uuid.uuid4()),
        operator_intent=(
            "preview_submit_and_safe_closeout_one_futures_order"
            if execute
            else "refresh_one_futures_manual_eligibility_cycle"
        ),
        authorize_preview_create_and_safe_closeout=execute,
        acknowledge_unknown_outcome_consumes_allowance=execute,
        acknowledge_create_requires_accepted_identical_preview=execute,
        acknowledge_cancel_is_only_for_exact_nonterminal_child=execute,
        authorize_one_no_retry_six_category_cycle=not execute,
        acknowledge_cycle_is_goal_global_and_limited_to_ten=not execute,
        acknowledge_unsuccessful_or_unknown_cycle_fails_closed=not execute,
    )


def _candidate(
    *,
    observed_at: datetime = TEST_NOW,
) -> dict[str, str]:
    return {
        "product_id": "AVP-20DEC30-CDE",
        "side": "BUY",
        "order_type": "LIMIT_GTC",
        "post_only": "true",
        "contract_count": "1",
        "limit_price": "6.45",
        "contract_size": "10",
        "opening_reference_notional_usdc": "64.80",
        "maximum_exposure_reference_notional_usdc": "129.60",
        "buffered_close_reference_notional_usdc": "129.60",
        "branch_turnover_reference_notional_usdc": "259.20",
        "opening_cap_usdc": "100",
        "exposure_cap_usdc": "150",
        "turnover_cap_usdc": "300",
        "observed_at": observed_at.isoformat(),
    }


def _eligible_result(
    *,
    candidate: dict[str, str] | None = None,
    portfolio_id: str = PORTFOLIO_ID,
) -> FuturesManualEligibilityResult:
    public = {
        "goal_id": "operator_futures_manual_order_lifecycle_v1",
        "profile_alias": "Default",
        "portfolio_type": "DEFAULT",
        "portfolio_id_sha256": hashlib.sha256(
            portfolio_id.encode("utf-8")
        ).hexdigest(),
        "credential_can_view": True,
        "credential_can_trade": True,
        "selection_authority": "cdp_api_key_permissioned_portfolio",
        "product_id": "AVP-20DEC30-CDE",
        "contract_count": "1",
        "caps": {
            "opening_usdc": "100",
            "exposure_usdc": "150",
            "turnover_usdc": "300",
            "comparison": "strictly_less_than",
        },
        "candidate": candidate or _candidate(),
        "exact_v3_eligible": True,
        "diagnostic_code": "operator_futures_manual_exact_v3_eligible",
        "category_attempts": {
            category: 1
            for category in FUTURES_MANUAL_ELIGIBILITY_CATEGORIES
        },
        "raw_responses_included": False,
        "private_identifiers_included": False,
        "exception_text_included": False,
    }
    encoded = json.dumps(
        public,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return FuturesManualEligibilityResult(
        outcome=AdminFuturesManualEligibilityOutcome.ELIGIBLE,
        diagnostic_code="operator_futures_manual_exact_v3_eligible",
        category_attempts={
            category: 1
            for category in FUTURES_MANUAL_ELIGIBILITY_CATEGORIES
        },
        candidate=candidate or _candidate(),
        portfolio_id_sha256=public["portfolio_id_sha256"],
        evidence_sha256=hashlib.sha256(encoded).hexdigest(),
        public_evidence=public,
    )


def _goal13_eligible_result(
    *,
    candidate_updates: dict[str, str] | None = None,
) -> FuturesManualEligibilityResult:
    parent_id = "11111111-1111-4111-8111-111111111111"
    window_id = "22222222-2222-4222-8222-222222222222"
    trigger_hash = "a" * 64
    portfolio_hash = hashlib.sha256(PORTFOLIO_ID.encode("utf-8")).hexdigest()
    candidate = {
        **_candidate(),
        "limit_price": "4.99",
        "product_price": "5",
        "reference_price": "5.01",
        "reference_price_source": (
            "max_product_price_and_fresh_best_ask"
        ),
        "price_increment": "0.01",
        "best_bid": "5.00",
        "best_ask": "5.01",
        "opening_reference_notional_usdc": "50.10",
        "maximum_exposure_reference_notional_usdc": "50.10",
        "buffered_close_reference_notional_usdc": "60.120",
        "branch_turnover_reference_notional_usdc": "110.220",
        "close_buffer_multiplier": "1.20",
        "product_policy_revision": str(FUTURES_HOTPOINT_POLICY_REVISION),
        "product_policy_sha256": FUTURES_HOTPOINT_POLICY_SHA256,
        "hotpoint_parent_client_order_id": parent_id,
        "hotpoint_window_id": window_id,
        "hotpoint_trigger_evidence_sha256": trigger_hash,
        "hotpoint_session_compatibility": "OPEN_24X7_GTC",
        "contract_expiry": "2030-12-20T00:00:00+00:00",
        "session_state": "FCM_TRADING_SESSION_STATE_OPEN",
        "session_is_open": "true",
        "after_hours_order_entry_disabled": "false",
        "session_closed_reason": "",
        "twenty_four_by_seven": "true",
        "maintenance_start": "",
        "maintenance_end": "",
        "session_observed_at": TEST_NOW.isoformat(),
    }
    candidate.update(candidate_updates or {})
    attempts = {
        category: 1 for category in FUTURES_MANUAL_ELIGIBILITY_CATEGORIES
    }
    public = {
        "goal_id": FUTURES_HOTPOINT_GOAL_ID,
        "profile_alias": "Default",
        "portfolio_type": "DEFAULT",
        "portfolio_id_sha256": portfolio_hash,
        "credential_can_view": True,
        "credential_can_trade": True,
        "selection_authority": "backend_futures_hotpoint_v2_policy",
        "product_id": "AVP-20DEC30-CDE",
        "contract_count": "1",
        "caps": {
            "opening_usdc": "100",
            "exposure_usdc": "150",
            "turnover_usdc": "300",
            "comparison": "strictly_less_than",
        },
        "candidate": candidate,
        "parent_client_order_id_sha256": hashlib.sha256(
            parent_id.encode("utf-8")
        ).hexdigest(),
        "window_id_sha256": hashlib.sha256(
            window_id.encode("utf-8")
        ).hexdigest(),
        "trigger_evidence_sha256": trigger_hash,
        "exact_v3_eligible": True,
        "diagnostic_code": "operator_futures_hotpoint_exact_v3_eligible",
        "category_attempts": attempts,
        "margin_subread_attempts": {
            "futures_balance_summary": 1,
            "intraday_margin_setting": 1,
            "current_margin_window_regular": 1,
            "current_margin_window_intraday": 1,
        },
        "raw_responses_included": False,
        "private_identifiers_included": False,
        "exception_text_included": False,
    }
    return FuturesManualEligibilityResult(
        outcome=AdminFuturesManualEligibilityOutcome.ELIGIBLE,
        diagnostic_code="operator_futures_hotpoint_exact_v3_eligible",
        category_attempts=attempts,
        candidate=candidate,
        portfolio_id_sha256=portfolio_hash,
        evidence_sha256=hashlib.sha256(
            json.dumps(
                public,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("utf-8")
        ).hexdigest(),
        public_evidence=public,
    )


def _unknown_result(
    attempts: dict[str, int],
    *,
    diagnostic: str = "operator_futures_manual_eligibility_read_unknown",
) -> FuturesManualEligibilityResult:
    public = {
        "goal_id": "operator_futures_manual_order_lifecycle_v1",
        "profile_alias": "Default",
        "product_id": "AVP-20DEC30-CDE",
        "contract_count": "1",
        "caps": {
            "opening_usdc": "100",
            "exposure_usdc": "150",
            "turnover_usdc": "300",
            "comparison": "strictly_less_than",
        },
        "exact_v3_eligible": False,
        "diagnostic_code": diagnostic,
        "category_attempts": attempts,
        "raw_responses_included": False,
        "private_identifiers_included": False,
        "exception_text_included": False,
    }
    encoded = json.dumps(
        public,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return FuturesManualEligibilityResult(
        outcome=AdminFuturesManualEligibilityOutcome.UNKNOWN,
        diagnostic_code=diagnostic,
        category_attempts=attempts,
        candidate=None,
        portfolio_id_sha256=None,
        evidence_sha256=hashlib.sha256(encoded).hexdigest(),
        public_evidence=public,
    )


def _complete_eligible_cycle(repository):
    initial = repository.read()
    claimed, cycle = repository.begin_eligibility_cycle(
        context=_context(revision=initial.revision, key="refresh-1")
    )
    assert claimed.cycles_used == 1
    assert cycle == 1
    for category in FUTURES_MANUAL_ELIGIBILITY_CATEGORIES:
        repository.claim_eligibility_category(
            cycle_number=cycle,
            category=category,
        )
    return repository.finish_eligibility_cycle(
        cycle_number=cycle,
        result=_eligible_result(),
        context=_context(
            revision=initial.revision,
            key="refresh-1",
        ),
    )


def _claim_goal13_eligibility_boundaries(repository, *, cycle: int) -> None:
    for category in FUTURES_MANUAL_ELIGIBILITY_CATEGORIES:
        repository.claim_eligibility_category(
            cycle_number=cycle,
            category=category,
        )
        if category == "futures_margin_collateral":
            for subread in FUTURES_MANUAL_MARGIN_SUBREADS:
                repository.claim_margin_subread(
                    cycle_number=cycle,
                    subread=subread,
                )


def _complete_goal13_eligible_cycle(repository, *, key: str):
    initial = repository.read()
    _, cycle = repository.begin_eligibility_cycle(
        context=_context(revision=initial.revision, key=key)
    )
    assert cycle == 1
    _claim_goal13_eligibility_boundaries(
        repository,
        cycle=cycle,
    )
    return repository.finish_eligibility_cycle(
        cycle_number=cycle,
        result=_goal13_eligible_result(),
        context=_context(revision=initial.revision, key=key),
    )


def test_initial_readback_has_exact_zeroed_category_accounting(repository):
    initial = repository.read()

    assert initial.category_attempts == {
        category: 0
        for category in FUTURES_MANUAL_ELIGIBILITY_CATEGORIES
    }
    assert initial.cycles_used == 0
    assert initial.active_cycle_number is None


def test_goal13_margin_subreads_are_durable_no_retry_restart_evidence(
    repository,
):
    goal13 = OperatorFuturesManualLifecycleRepository(
        _database(),
        schema=repository.schema,
        configured_portfolio_id=PORTFOLIO_ID,
        clock=lambda: TEST_NOW,
        goal_id=FUTURES_HOTPOINT_GOAL_ID,
        eligibility_evidence_validator=(
            validate_futures_hotpoint_eligibility_evidence
        ),
        claim_validator=lambda *, cursor, candidate: (
            validate_futures_hotpoint_candidate(candidate)
        ),
        preview_invocation_validator=lambda **_kwargs: None,
        create_invocation_validator=lambda **_kwargs: None,
        client_order_id_prefix="operator-futures-hotpoint-v2-",
    )
    goal13.ensure_schema()
    try:
        initial = goal13.read()
        assert initial.margin_subread_attempts == {
            subread: 0 for subread in FUTURES_MANUAL_MARGIN_SUBREADS
        }
        _claimed, cycle = goal13.begin_eligibility_cycle(
            context=_context(
                revision=initial.revision,
                key="goal13-margin-partial",
            )
        )
        assert cycle == 1
        goal13.claim_eligibility_category(
            cycle_number=cycle,
            category="futures_margin_collateral",
        )
        for subread in FUTURES_MANUAL_MARGIN_SUBREADS[:2]:
            goal13.claim_margin_subread(
                cycle_number=cycle,
                subread=subread,
            )
        with pytest.raises(
            ValueError,
            match=(
                "operator_futures_manual_margin_subread_"
                "already_claimed"
            ),
        ):
            goal13.claim_margin_subread(
                cycle_number=cycle,
                subread=FUTURES_MANUAL_MARGIN_SUBREADS[0],
            )
        assert goal13.read().margin_subread_attempts == {
            FUTURES_MANUAL_MARGIN_SUBREADS[0]: 1,
            FUTURES_MANUAL_MARGIN_SUBREADS[1]: 1,
            FUTURES_MANUAL_MARGIN_SUBREADS[2]: 0,
            FUTURES_MANUAL_MARGIN_SUBREADS[3]: 0,
        }
    finally:
        goal13.db.disconnect()

    restarted = OperatorFuturesManualLifecycleRepository(
        _database(),
        schema=repository.schema,
        configured_portfolio_id=PORTFOLIO_ID,
        clock=lambda: TEST_NOW,
        goal_id=FUTURES_HOTPOINT_GOAL_ID,
        eligibility_evidence_validator=(
            validate_futures_hotpoint_eligibility_evidence
        ),
        claim_validator=lambda *, cursor, candidate: (
            validate_futures_hotpoint_candidate(candidate)
        ),
        preview_invocation_validator=lambda **_kwargs: None,
        create_invocation_validator=lambda **_kwargs: None,
        client_order_id_prefix="operator-futures-hotpoint-v2-",
    )
    restarted.ensure_schema()
    try:
        recovered = restarted.read()
        assert recovered.active_cycle_number is None
        assert recovered.eligibility_outcome is (
            AdminFuturesManualEligibilityOutcome.UNKNOWN
        )
        assert recovered.eligibility_diagnostic_code == (
            "operator_futures_manual_restart_eligibility_unknown"
        )
        assert recovered.margin_subread_attempts == {
            FUTURES_MANUAL_MARGIN_SUBREADS[0]: 1,
            FUTURES_MANUAL_MARGIN_SUBREADS[1]: 1,
            FUTURES_MANUAL_MARGIN_SUBREADS[2]: 0,
            FUTURES_MANUAL_MARGIN_SUBREADS[3]: 0,
        }
        with pytest.raises(
            ValueError,
            match="operator_futures_manual_cycle_not_active",
        ):
            restarted.claim_margin_subread(
                cycle_number=cycle,
                subread=FUTURES_MANUAL_MARGIN_SUBREADS[2],
            )
    finally:
        restarted.db.disconnect()


def test_cycle_is_exact_idempotent_and_restart_durable(repository):
    eligible = _complete_eligible_cycle(repository)

    assert eligible.revision == 2
    assert eligible.cycles_used == 1
    assert (
        eligible.eligibility_outcome
        is AdminFuturesManualEligibilityOutcome.ELIGIBLE
    )
    assert eligible.candidate == _candidate()
    assert PORTFOLIO_ID not in repr(eligible)

    replay, replay_cycle = repository.begin_eligibility_cycle(
        context=_context(revision=0, key="refresh-1")
    )
    assert replay_cycle is None
    assert replay == eligible

    restarted = OperatorFuturesManualLifecycleRepository(
        _database(),
        schema=repository.schema,
        configured_portfolio_id=None,
        clock=lambda: TEST_NOW,
    )
    restarted.ensure_schema()
    try:
        assert restarted.read() == eligible
    finally:
        restarted.db.disconnect()


def test_first_default_portfolio_hash_binding_rejects_later_drift(repository):
    eligible = _complete_eligible_cycle(repository)
    claimed, cycle = repository.begin_eligibility_cycle(
        context=_context(
            revision=eligible.revision,
            key="refresh-portfolio-drift",
        )
    )
    assert cycle == 2
    for category in FUTURES_MANUAL_ELIGIBILITY_CATEGORIES:
        repository.claim_eligibility_category(
            cycle_number=cycle,
            category=category,
        )

    with pytest.raises(
        ValueError,
        match="operator_futures_manual_eligible_evidence_invalid",
    ):
        repository.finish_eligibility_cycle(
            cycle_number=cycle,
            result=_eligible_result(
                portfolio_id="99999999-8888-4777-8666-555555555555"
            ),
            context=_context(
                revision=claimed.revision,
                key="refresh-portfolio-drift",
            ),
        )


def test_configured_default_portfolio_must_match_durable_hash_binding(repository):
    _complete_eligible_cycle(repository)
    mismatched = OperatorFuturesManualLifecycleRepository(
        _database(),
        schema=repository.schema,
        configured_portfolio_id="99999999-8888-4777-8666-555555555555",
        clock=lambda: TEST_NOW,
    )
    try:
        with pytest.raises(
            RuntimeError,
            match="operator_futures_manual_portfolio_binding_invalid",
        ):
            mismatched.ensure_schema()
    finally:
        mismatched.db.disconnect()


def test_category_is_single_use_and_unapproved_reads_fail_closed(repository):
    initial = repository.read()
    _, cycle = repository.begin_eligibility_cycle(
        context=_context(revision=initial.revision, key="refresh-1")
    )
    assert cycle == 1
    repository.claim_eligibility_category(
        cycle_number=cycle,
        category="api_key_permissions",
    )

    with pytest.raises(
        ValueError,
        match="operator_futures_manual_category_already_claimed",
    ):
        repository.claim_eligibility_category(
            cycle_number=cycle,
            category="api_key_permissions",
        )
    with pytest.raises(
        ValueError,
        match="operator_futures_manual_category_not_authorized",
    ):
        repository.claim_eligibility_category(
            cycle_number=cycle,
            category="list_futures_sweeps",
        )


def test_early_read_failure_persists_exact_six_category_accounting(repository):
    initial = repository.read()
    _, cycle = repository.begin_eligibility_cycle(
        context=_context(revision=initial.revision, key="refresh-early-failure")
    )
    assert cycle == 1
    attempted = {
        category: 0
        for category in FUTURES_MANUAL_ELIGIBILITY_CATEGORIES
    }
    for category in FUTURES_MANUAL_ELIGIBILITY_CATEGORIES[:3]:
        repository.claim_eligibility_category(
            cycle_number=cycle,
            category=category,
        )
        attempted[category] = 1

    finished = repository.finish_eligibility_cycle(
        cycle_number=cycle,
        result=_unknown_result(attempted),
        context=_context(
            revision=initial.revision,
            key="refresh-early-failure",
        ),
    )

    assert finished.eligibility_outcome is (
        AdminFuturesManualEligibilityOutcome.UNKNOWN
    )
    assert finished.category_attempts == attempted


def test_terminal_positions_forbidden_durably_closes_refresh_authority(
    repository,
):
    initial = repository.read()
    _, cycle = repository.begin_eligibility_cycle(
        context=_context(revision=initial.revision, key="refresh-forbidden")
    )
    assert cycle == 1
    attempted = {
        category: int(
            category != "futures_margin_collateral"
        )
        for category in FUTURES_MANUAL_ELIGIBILITY_CATEGORIES
    }
    for category, count in attempted.items():
        if count:
            repository.claim_eligibility_category(
                cycle_number=cycle,
                category=category,
            )
    finished = repository.finish_eligibility_cycle(
        cycle_number=cycle,
        result=_unknown_result(
            attempted,
            diagnostic=(
                "operator_futures_manual_futures_positions_http_forbidden"
            ),
        ),
        context=_context(
            revision=initial.revision,
            key="refresh-forbidden",
        ),
    )

    with pytest.raises(
        ValueError,
        match="operator_futures_manual_goal_terminal",
    ):
        repository.begin_eligibility_cycle(
            context=_context(
                revision=finished.revision,
                key="refresh-after-forbidden",
            )
        )

    restarted = OperatorFuturesManualLifecycleRepository(
        _database(),
        schema=repository.schema,
        configured_portfolio_id=None,
        clock=lambda: TEST_NOW,
    )
    restarted.ensure_schema()
    try:
        with pytest.raises(
            ValueError,
            match="operator_futures_manual_goal_terminal",
        ):
            restarted.begin_eligibility_cycle(
                context=_context(
                    revision=finished.revision,
                    key="refresh-after-restart",
                )
            )
    finally:
        restarted.db.disconnect()


def test_active_successor_starts_unconsumed_without_changing_terminal_predecessor(
    repository,
):
    initial = repository.read()
    _, cycle = repository.begin_eligibility_cycle(
        context=_context(
            revision=initial.revision,
            key="terminal-predecessor",
        )
    )
    assert cycle == 1
    attempts = {
        category: int(category != "futures_margin_collateral")
        for category in FUTURES_MANUAL_ELIGIBILITY_CATEGORIES
    }
    for category, count in attempts.items():
        if count:
            repository.claim_eligibility_category(
                cycle_number=cycle,
                category=category,
            )
    predecessor = repository.finish_eligibility_cycle(
        cycle_number=cycle,
        result=_unknown_result(
            attempts,
            diagnostic=(
                "operator_futures_manual_futures_positions_http_forbidden"
            ),
        ),
        context=_context(
            revision=initial.revision,
            key="terminal-predecessor",
        ),
    )

    successor = OperatorFuturesManualLifecycleRepository(
        _database(),
        schema=repository.schema,
        configured_portfolio_id=None,
        clock=lambda: TEST_NOW,
        goal_id=FUTURES_MANUAL_ACTIVE_GOAL_ID,
    )
    successor.ensure_schema()
    try:
        successor_record = successor.read()
        assert successor_record.goal_id == FUTURES_MANUAL_ACTIVE_GOAL_ID
        assert successor_record.revision == 0
        assert successor_record.cycles_used == 0
        assert successor_record.preview_outcome is (
            AdminFuturesManualCallOutcome.NOT_RUN
        )
        assert successor_record.create_outcome is (
            AdminFuturesManualCallOutcome.NOT_RUN
        )
        assert repository.read() == predecessor
    finally:
        successor.db.disconnect()


def test_preview_create_reconcile_and_exact_cancel_are_single_use(repository):
    eligible = _complete_eligible_cycle(repository)
    record, plan = repository.claim_preview(
        context=_context(
            revision=eligible.revision,
            key="execute-1",
            execute=True,
        )
    )
    assert plan is not None
    assert record.preview_outcome is AdminFuturesManualCallOutcome.CLAIMED

    repository.mark_preview_exchange_invoked(claim_id=plan.claim_id)
    record = repository.finish_preview(
        claim_id=plan.claim_id,
        execution=FuturesManualPreviewExecution(
            outcome=AdminFuturesManualCallOutcome.ACCEPTED,
            diagnostic_code="operator_futures_manual_preview_accepted",
            preview_id_sha256="d" * 64,
            public_evidence={},
        ),
    )
    assert record.preview_exchange_invoked is True
    assert record.preview_id_sha256 == "d" * 64

    repository.claim_create(claim_id=plan.claim_id)
    repository.mark_create_exchange_invoked(claim_id=plan.claim_id)
    record = repository.finish_create_and_claim_reconciliation(
        claim_id=plan.claim_id,
        execution=FuturesManualCreateExecution(
            outcome=AdminFuturesManualCallOutcome.ACCEPTED,
            diagnostic_code="operator_futures_manual_create_accepted",
            exchange_order_id_sha256="e" * 64,
            public_evidence={},
        ),
    )
    assert record.create_exchange_invoked is True
    assert (
        record.reconciliation_outcome
        is AdminFuturesManualCallOutcome.CLAIMED
    )

    repository.mark_reconciliation_exchange_invoked(
        claim_id=plan.claim_id
    )
    record = repository.finish_reconciliation_and_claim_cancel(
        claim_id=plan.claim_id,
        execution=FuturesManualReconciliationExecution(
            outcome=AdminFuturesManualCallOutcome.ACCEPTED,
            diagnostic_code=(
                "operator_futures_manual_reconciliation_accepted"
            ),
            exchange_order_id_sha256="e" * 64,
            order_status="OPEN",
            authoritatively_nonterminal=True,
            public_evidence={},
        ),
    )
    assert record.order_status == "OPEN"
    assert record.authoritatively_nonterminal is True
    assert record.cancel_outcome is AdminFuturesManualCallOutcome.CLAIMED

    repository.mark_cancel_exchange_invoked(claim_id=plan.claim_id)
    record = repository.finish_cancel(
        claim_id=plan.claim_id,
        execution=FuturesManualCancelExecution(
            outcome=AdminFuturesManualCallOutcome.ACCEPTED,
            diagnostic_code="operator_futures_manual_cancel_accepted",
            exchange_order_id_sha256="e" * 64,
            public_evidence={},
        ),
    )
    assert record.cancel_outcome is AdminFuturesManualCallOutcome.ACCEPTED

    replay, replay_plan = repository.claim_preview(
        context=_context(
            revision=eligible.revision,
            key="execute-1",
            execute=True,
        )
    )
    assert replay_plan is None
    assert replay == record


def test_accepted_preview_atomically_claims_the_single_create(repository):
    eligible = _complete_eligible_cycle(repository)
    _, plan = repository.claim_preview(
        context=_context(
            revision=eligible.revision,
            key="execute-atomic-preview-create",
            execute=True,
        )
    )
    assert plan is not None
    repository.mark_preview_exchange_invoked(claim_id=plan.claim_id)

    record = repository.finish_preview_and_claim_create(
        claim_id=plan.claim_id,
        execution=FuturesManualPreviewExecution(
            outcome=AdminFuturesManualCallOutcome.ACCEPTED,
            diagnostic_code="operator_futures_manual_preview_accepted",
            preview_id_sha256="d" * 64,
            public_evidence={},
        ),
    )

    assert record.preview_outcome is AdminFuturesManualCallOutcome.ACCEPTED
    assert record.preview_exchange_invoked is True
    assert record.preview_id_sha256 == "d" * 64
    assert record.create_outcome is AdminFuturesManualCallOutcome.CLAIMED
    assert record.create_exchange_invoked is False
    with pytest.raises(
        ValueError,
        match="operator_futures_manual_create_already_claimed",
    ):
        repository.claim_create(claim_id=plan.claim_id)


def test_atomic_preview_to_create_claim_rechecks_candidate_freshness(
    repository,
):
    eligible = _complete_eligible_cycle(repository)
    _, plan = repository.claim_preview(
        context=_context(
            revision=eligible.revision,
            key="execute-stale-after-preview",
            execute=True,
        )
    )
    assert plan is not None
    repository.mark_preview_exchange_invoked(claim_id=plan.claim_id)
    repository.clock = lambda: TEST_NOW + timedelta(seconds=31)

    with pytest.raises(
        ValueError,
        match="operator_futures_manual_candidate_stale",
    ):
        repository.finish_preview_and_claim_create(
            claim_id=plan.claim_id,
            execution=FuturesManualPreviewExecution(
                outcome=AdminFuturesManualCallOutcome.ACCEPTED,
                diagnostic_code="operator_futures_manual_preview_accepted",
                preview_id_sha256="d" * 64,
                public_evidence={},
            ),
        )

    unchanged = repository.read()
    assert unchanged.preview_outcome is AdminFuturesManualCallOutcome.CLAIMED
    assert unchanged.create_outcome is AdminFuturesManualCallOutcome.NOT_RUN


def test_goal13_unknown_create_can_only_close_out_through_exact_reconciliation(
    repository,
):
    predecessor = repository.read()
    goal13 = OperatorFuturesManualLifecycleRepository(
        _database(),
        schema=repository.schema,
        configured_portfolio_id=PORTFOLIO_ID,
        clock=lambda: TEST_NOW,
        goal_id=FUTURES_HOTPOINT_GOAL_ID,
        eligibility_evidence_validator=(
            validate_futures_hotpoint_eligibility_evidence
        ),
        claim_validator=lambda *, cursor, candidate: (
            validate_futures_hotpoint_candidate(candidate)
        ),
        preview_invocation_validator=lambda **_kwargs: None,
        create_invocation_validator=lambda **_kwargs: None,
        client_order_id_prefix="operator-futures-hotpoint-v2-",
    )
    goal13.ensure_schema()
    try:
        initial = goal13.read()
        external_context = _context(
            revision=initial.revision,
            key="goal13-external-run",
        )
        external_payload = {
            "expected_revision": 2,
            "expected_parent_client_order_id": (
                "11111111-1111-4111-8111-111111111111"
            ),
            "confirm_bounded_trigger_evaluation": True,
        }
        first_command = goal13.claim_hotpoint_external_command(
            action="RUN_ONCE",
            context=external_context,
            request_payload=external_payload,
        )
        assert first_command.status == "NEW"
        pending_command = goal13.claim_hotpoint_external_command(
            action="RUN_ONCE",
            context=external_context,
            request_payload=external_payload,
        )
        assert pending_command.command_id == first_command.command_id
        assert pending_command.status == "IN_PROGRESS"
        goal13.finish_hotpoint_external_command(
            command_id=first_command.command_id,
            outcome="SUCCESS",
            result_snapshot={
                "goal_id": FUTURES_HOTPOINT_GOAL_ID,
                "diagnostic_code": (
                    "operator_futures_hotpoint_command_completed"
                ),
            },
            error_code=None,
            http_status_code=None,
        )
        replayed_command = goal13.claim_hotpoint_external_command(
            action="RUN_ONCE",
            context=external_context,
            request_payload=external_payload,
        )
        assert replayed_command.status == "SUCCESS"
        assert replayed_command.result_snapshot == {
            "goal_id": FUTURES_HOTPOINT_GOAL_ID,
            "diagnostic_code": (
                "operator_futures_hotpoint_command_completed"
            ),
        }
        with pytest.raises(
            ValueError,
            match="operator_futures_hotpoint_idempotency_conflict",
        ):
            goal13.claim_hotpoint_external_command(
                action="RUN_ONCE",
                context=external_context,
                request_payload={
                    **external_payload,
                    "expected_revision": 3,
                },
            )
        with pytest.raises(
            ValueError,
            match="operator_futures_hotpoint_idempotency_conflict",
        ):
            goal13.claim_hotpoint_external_command(
                action="RUN_ONCE",
                context=replace(
                    external_context,
                    actor_id="operator-2",
                ),
                request_payload=external_payload,
            )
        _, cycle = goal13.begin_eligibility_cycle(
            context=_context(revision=initial.revision, key="goal13-refresh")
        )
        assert cycle == 1
        _claim_goal13_eligibility_boundaries(
            goal13,
            cycle=cycle,
        )
        eligible = goal13.finish_eligibility_cycle(
            cycle_number=cycle,
            result=_goal13_eligible_result(),
            context=_context(revision=initial.revision, key="goal13-refresh"),
        )
        _, plan = goal13.claim_preview(
            context=_context(
                revision=eligible.revision,
                key="goal13-execute",
                execute=True,
            )
        )
        assert plan is not None
        goal13.mark_preview_exchange_invoked(claim_id=plan.claim_id)
        goal13.finish_preview_and_claim_create(
            claim_id=plan.claim_id,
            execution=FuturesManualPreviewExecution(
                outcome=AdminFuturesManualCallOutcome.ACCEPTED,
                diagnostic_code=(
                    "operator_futures_hotpoint_preview_accepted"
                ),
                preview_id_sha256="d" * 64,
                public_evidence={},
            ),
        )
        goal13.mark_create_exchange_invoked(claim_id=plan.claim_id)
        unknown = goal13.finish_create(
            claim_id=plan.claim_id,
            execution=FuturesManualCreateExecution(
                outcome=AdminFuturesManualCallOutcome.UNKNOWN,
                diagnostic_code=(
                    "operator_futures_product_ticket_create_outcome_unknown"
                ),
                exchange_order_id_sha256=None,
                public_evidence={},
            ),
        )
        assert unknown.create_outcome is AdminFuturesManualCallOutcome.UNKNOWN
        assert unknown.reconciliation_outcome is (
            AdminFuturesManualCallOutcome.NOT_RUN
        )

        safe_context = replace(
            _context(
                revision=unknown.revision,
                key="goal13-safe-closeout",
                execute=True,
            ),
            actor_id="operator-safe",
            correlation_id="corr-goal13-safe-closeout",
            audit_id="66666666-6666-4666-8666-666666666666",
            operator_intent=(
                HOTPOINT_SAFE_CLOSEOUT_OPERATOR_INTENT
            ),
        )
        reconciliation_claim = goal13.claim_reconciliation(
            claim_id=plan.claim_id,
            context=safe_context,
        )
        assert reconciliation_claim.reconciliation_catalog_end_at == (
            TEST_NOW.isoformat()
        )
        assert reconciliation_claim.correlation_id == (
            "corr-goal13-safe-closeout"
        )
        assert reconciliation_claim.audit_id == (
            "66666666-6666-4666-8666-666666666666"
        )
        goal13.mark_reconciliation_exchange_invoked(claim_id=plan.claim_id)
        reconciled = goal13.finish_reconciliation_and_claim_cancel(
            claim_id=plan.claim_id,
            execution=FuturesHotpointReconciliationExecution(
                outcome=AdminFuturesManualCallOutcome.ACCEPTED,
                diagnostic_code=(
                    "operator_futures_hotpoint_reconciliation_accepted"
                ),
                exchange_order_id_sha256="e" * 64,
                order_status="OPEN",
                authoritatively_nonterminal=True,
                public_evidence={},
                private_exchange_order_id="ephemeral-private-order-id",
            ),
        )
        assert reconciled.create_outcome is (
            AdminFuturesManualCallOutcome.ACCEPTED
        )
        assert reconciled.exchange_order_id_sha256 == "e" * 64
        assert reconciled.cancel_outcome is (
            AdminFuturesManualCallOutcome.CLAIMED
        )
        goal13.mark_cancel_exchange_invoked(claim_id=plan.claim_id)
        closed = goal13.finish_cancel(
            claim_id=plan.claim_id,
            execution=FuturesManualCancelExecution(
                outcome=AdminFuturesManualCallOutcome.ACCEPTED,
                diagnostic_code=(
                    "operator_futures_product_ticket_cancel_accepted"
                ),
                exchange_order_id_sha256="e" * 64,
                public_evidence={},
            ),
        )
        assert closed.cancel_outcome is AdminFuturesManualCallOutcome.ACCEPTED
        assert closed.correlation_id == "corr-goal13-safe-closeout"
        assert closed.audit_id == (
            "66666666-6666-4666-8666-666666666666"
        )
    finally:
        goal13.db.disconnect()
    assert repository.read() == predecessor


def test_goal13_external_command_recovery_is_terminal_and_no_replay(
    repository,
):
    goal13 = OperatorFuturesManualLifecycleRepository(
        _database(),
        schema=repository.schema,
        configured_portfolio_id=PORTFOLIO_ID,
        clock=lambda: TEST_NOW,
        goal_id=FUTURES_HOTPOINT_GOAL_ID,
        eligibility_evidence_validator=(
            validate_futures_hotpoint_eligibility_evidence
        ),
        claim_validator=lambda *, cursor, candidate: (
            validate_futures_hotpoint_candidate(candidate)
        ),
        preview_invocation_validator=lambda **_kwargs: None,
        create_invocation_validator=lambda **_kwargs: None,
        client_order_id_prefix="operator-futures-hotpoint-v2-",
    )
    goal13.ensure_schema()
    try:
        context = _context(
            revision=goal13.read().revision,
            key="goal13-external-recovery",
        )
        payload = {
            "expected_revision": 2,
            "expected_parent_client_order_id": (
                "11111111-1111-4111-8111-111111111111"
            ),
        }
        claimed = goal13.claim_hotpoint_external_command(
            action="RUN_ONCE",
            context=context,
            request_payload=payload,
        )
        assert claimed.status == "NEW"

        goal13.recover_hotpoint_external_commands()

        recovered = goal13.claim_hotpoint_external_command(
            action="RUN_ONCE",
            context=context,
            request_payload=payload,
        )
        assert recovered.command_id == claimed.command_id
        assert recovered.status == "UNKNOWN"
        assert recovered.error_code == (
            "operator_futures_hotpoint_command_outcome_unknown"
        )
        assert recovered.http_status_code == 503
        assert goal13.read_latest_hotpoint_external_command() == (
            FuturesHotpointExternalCommandReadback(
                action="RUN_ONCE",
                status="UNKNOWN",
                correlation_id=context.correlation_id,
                request_revision=context.expected_revision,
                diagnostic_code=(
                    "operator_futures_hotpoint_command_outcome_unknown"
                ),
            )
        )
        with pytest.raises(
            ValueError,
            match="operator_futures_hotpoint_external_result_conflict",
        ):
            goal13.finish_hotpoint_external_command(
                command_id=claimed.command_id,
                outcome="SUCCESS",
                result_snapshot={"unexpected": "replay"},
                error_code=None,
                http_status_code=None,
            )
        with pytest.raises(
            ValueError,
            match="operator_futures_hotpoint_external_result_invalid",
        ):
            goal13.finish_hotpoint_external_command(
                command_id=claimed.command_id,
                outcome="UNKNOWN",
                result_snapshot=None,
                error_code="withheld",
                http_status_code=503,
            )
    finally:
        goal13.db.disconnect()


def test_goal13_revocation_after_preview_blocks_create_invocation(
    repository,
):
    revoked = False
    observed: dict[str, object] = {}

    def validate_create_invocation(
        *,
        cursor,
        candidate,
        claim_id,
        client_order_id,
    ) -> None:
        del cursor
        observed.update(
            {
                "candidate": dict(candidate),
                "claim_id": claim_id,
                "client_order_id": client_order_id,
            }
        )
        if revoked:
            raise ValueError(
                "operator_futures_hotpoint_create_invocation_not_authorized"
            )

    goal13 = OperatorFuturesManualLifecycleRepository(
        _database(),
        schema=repository.schema,
        configured_portfolio_id=PORTFOLIO_ID,
        clock=lambda: TEST_NOW,
        goal_id=FUTURES_HOTPOINT_GOAL_ID,
        eligibility_evidence_validator=(
            validate_futures_hotpoint_eligibility_evidence
        ),
        claim_validator=lambda *, cursor, candidate: (
            validate_futures_hotpoint_candidate(candidate)
        ),
        preview_invocation_validator=lambda **_kwargs: None,
        create_invocation_validator=validate_create_invocation,
        client_order_id_prefix="operator-futures-hotpoint-v2-",
    )
    goal13.ensure_schema()
    try:
        initial = goal13.read()
        _, cycle = goal13.begin_eligibility_cycle(
            context=_context(
                revision=initial.revision,
                key="goal13-revocation-refresh",
            )
        )
        assert cycle == 1
        _claim_goal13_eligibility_boundaries(
            goal13,
            cycle=cycle,
        )
        eligible = goal13.finish_eligibility_cycle(
            cycle_number=cycle,
            result=_goal13_eligible_result(),
            context=_context(
                revision=initial.revision,
                key="goal13-revocation-refresh",
            ),
        )
        _, plan = goal13.claim_preview(
            context=_context(
                revision=eligible.revision,
                key="goal13-revocation-execute",
                execute=True,
            )
        )
        assert plan is not None
        goal13.mark_preview_exchange_invoked(claim_id=plan.claim_id)
        claimed = goal13.finish_preview_and_claim_create(
            claim_id=plan.claim_id,
            execution=FuturesManualPreviewExecution(
                outcome=AdminFuturesManualCallOutcome.ACCEPTED,
                diagnostic_code=(
                    "operator_futures_hotpoint_preview_accepted"
                ),
                preview_id_sha256="d" * 64,
                public_evidence={},
            ),
        )
        assert claimed.preview_outcome is (
            AdminFuturesManualCallOutcome.ACCEPTED
        )
        assert claimed.create_outcome is (
            AdminFuturesManualCallOutcome.CLAIMED
        )

        revoked = True
        with pytest.raises(
            ValueError,
            match=(
                "operator_futures_hotpoint_create_invocation_"
                "not_authorized"
            ),
        ):
            goal13.mark_create_exchange_invoked(
                claim_id=plan.claim_id
            )

        blocked = goal13.read()
        assert blocked.preview_outcome is (
            AdminFuturesManualCallOutcome.ACCEPTED
        )
        assert blocked.create_outcome is (
            AdminFuturesManualCallOutcome.CLAIMED
        )
        assert blocked.create_exchange_invoked is False
        assert observed == {
            "candidate": plan.candidate,
            "claim_id": plan.claim_id,
            "client_order_id": plan.client_order_id,
        }
    finally:
        goal13.db.disconnect()


def test_goal13_revocation_at_preview_boundary_keeps_preview_unentered(
    repository,
):
    revoked = False

    def validate_preview_invocation(**_kwargs) -> None:
        if revoked:
            raise ValueError(
                "operator_futures_hotpoint_preview_invocation_not_authorized"
            )

    goal13 = OperatorFuturesManualLifecycleRepository(
        _database(),
        schema=repository.schema,
        configured_portfolio_id=PORTFOLIO_ID,
        clock=lambda: TEST_NOW,
        goal_id=FUTURES_HOTPOINT_GOAL_ID,
        eligibility_evidence_validator=(
            validate_futures_hotpoint_eligibility_evidence
        ),
        claim_validator=lambda *, cursor, candidate: (
            validate_futures_hotpoint_candidate(candidate)
        ),
        preview_invocation_validator=validate_preview_invocation,
        create_invocation_validator=lambda **_kwargs: None,
        client_order_id_prefix="operator-futures-hotpoint-v2-",
    )
    goal13.ensure_schema()
    try:
        initial = goal13.read()
        _, cycle = goal13.begin_eligibility_cycle(
            context=_context(
                revision=initial.revision,
                key="goal13-preview-revocation-refresh",
            )
        )
        assert cycle == 1
        _claim_goal13_eligibility_boundaries(
            goal13,
            cycle=cycle,
        )
        eligible = goal13.finish_eligibility_cycle(
            cycle_number=cycle,
            result=_goal13_eligible_result(),
            context=_context(
                revision=initial.revision,
                key="goal13-preview-revocation-refresh",
            ),
        )
        _, plan = goal13.claim_preview(
            context=_context(
                revision=eligible.revision,
                key="goal13-preview-revocation-execute",
                execute=True,
            )
        )
        assert plan is not None

        revoked = True
        with pytest.raises(
            ValueError,
            match=(
                "operator_futures_hotpoint_preview_invocation_"
                "not_authorized"
            ),
        ):
            goal13.mark_preview_exchange_invoked(
                claim_id=plan.claim_id
            )

        blocked = goal13.read()
        assert blocked.preview_outcome is (
            AdminFuturesManualCallOutcome.CLAIMED
        )
        assert blocked.preview_exchange_invoked is False
        assert blocked.create_outcome is (
            AdminFuturesManualCallOutcome.NOT_RUN
        )
        assert blocked.create_exchange_invoked is None
    finally:
        goal13.db.disconnect()


def test_goal13_preview_marker_rechecks_freshness_before_sdk_boundary(
    repository,
):
    current_time = [TEST_NOW]
    validator_calls: list[str] = []
    goal13 = OperatorFuturesManualLifecycleRepository(
        _database(),
        schema=repository.schema,
        configured_portfolio_id=PORTFOLIO_ID,
        clock=lambda: current_time[0],
        goal_id=FUTURES_HOTPOINT_GOAL_ID,
        eligibility_evidence_validator=(
            validate_futures_hotpoint_eligibility_evidence
        ),
        claim_validator=lambda *, cursor, candidate: (
            validate_futures_hotpoint_candidate(candidate)
        ),
        preview_invocation_validator=lambda **_kwargs: (
            validator_calls.append("preview")
        ),
        create_invocation_validator=lambda **_kwargs: None,
        client_order_id_prefix="operator-futures-hotpoint-v2-",
    )
    goal13.ensure_schema()
    try:
        eligible = _complete_goal13_eligible_cycle(
            goal13,
            key="goal13-preview-marker-freshness-refresh",
        )
        _, plan = goal13.claim_preview(
            context=_context(
                revision=eligible.revision,
                key="goal13-preview-marker-freshness-execute",
                execute=True,
            )
        )
        assert plan is not None

        current_time[0] = TEST_NOW + timedelta(seconds=31)
        with pytest.raises(
            ValueError,
            match="operator_futures_manual_candidate_stale",
        ):
            goal13.mark_preview_exchange_invoked(
                claim_id=plan.claim_id
            )

        blocked = goal13.read()
        assert blocked.preview_outcome is (
            AdminFuturesManualCallOutcome.CLAIMED
        )
        assert blocked.preview_exchange_invoked is False
        assert blocked.create_outcome is (
            AdminFuturesManualCallOutcome.NOT_RUN
        )
        assert validator_calls == []
    finally:
        goal13.db.disconnect()


def test_goal13_create_marker_rechecks_freshness_before_sdk_boundary(
    repository,
):
    current_time = [TEST_NOW]
    validator_calls: list[str] = []
    goal13 = OperatorFuturesManualLifecycleRepository(
        _database(),
        schema=repository.schema,
        configured_portfolio_id=PORTFOLIO_ID,
        clock=lambda: current_time[0],
        goal_id=FUTURES_HOTPOINT_GOAL_ID,
        eligibility_evidence_validator=(
            validate_futures_hotpoint_eligibility_evidence
        ),
        claim_validator=lambda *, cursor, candidate: (
            validate_futures_hotpoint_candidate(candidate)
        ),
        preview_invocation_validator=lambda **_kwargs: None,
        create_invocation_validator=lambda **_kwargs: (
            validator_calls.append("create")
        ),
        client_order_id_prefix="operator-futures-hotpoint-v2-",
    )
    goal13.ensure_schema()
    try:
        eligible = _complete_goal13_eligible_cycle(
            goal13,
            key="goal13-create-marker-freshness-refresh",
        )
        _, plan = goal13.claim_preview(
            context=_context(
                revision=eligible.revision,
                key="goal13-create-marker-freshness-execute",
                execute=True,
            )
        )
        assert plan is not None
        goal13.mark_preview_exchange_invoked(claim_id=plan.claim_id)
        goal13.finish_preview_and_claim_create(
            claim_id=plan.claim_id,
            execution=FuturesManualPreviewExecution(
                outcome=AdminFuturesManualCallOutcome.ACCEPTED,
                diagnostic_code=(
                    "operator_futures_hotpoint_preview_accepted"
                ),
                preview_id_sha256="d" * 64,
                public_evidence={},
            ),
        )

        current_time[0] = TEST_NOW + timedelta(seconds=31)
        with pytest.raises(
            ValueError,
            match="operator_futures_manual_candidate_stale",
        ):
            goal13.mark_create_exchange_invoked(
                claim_id=plan.claim_id
            )

        blocked = goal13.read()
        assert blocked.preview_outcome is (
            AdminFuturesManualCallOutcome.ACCEPTED
        )
        assert blocked.create_outcome is (
            AdminFuturesManualCallOutcome.CLAIMED
        )
        assert blocked.create_exchange_invoked is False
        assert validator_calls == []
    finally:
        goal13.db.disconnect()


@pytest.mark.parametrize(
    "candidate_updates",
    (
        {
            "maintenance_start": "2026-07-24T12:00:20Z",
            "maintenance_end": "2026-07-24T12:01:20Z",
        },
        {"contract_expiry": "2026-07-24T12:00:20Z"},
    ),
)
def test_goal13_preview_marker_rechecks_session_and_expiry_boundaries(
    repository,
    candidate_updates,
):
    current_time = [TEST_NOW]
    goal13 = OperatorFuturesManualLifecycleRepository(
        _database(),
        schema=repository.schema,
        configured_portfolio_id=PORTFOLIO_ID,
        clock=lambda: current_time[0],
        goal_id=FUTURES_HOTPOINT_GOAL_ID,
        eligibility_evidence_validator=(
            validate_futures_hotpoint_eligibility_evidence
        ),
        claim_validator=lambda *, cursor, candidate: (
            validate_futures_hotpoint_candidate(candidate)
        ),
        preview_invocation_validator=lambda *, cursor, candidate: (
            validate_futures_hotpoint_candidate_execution_window(
                candidate,
                now=current_time[0],
            )
        ),
        create_invocation_validator=lambda **_kwargs: None,
        client_order_id_prefix="operator-futures-hotpoint-v2-",
    )
    goal13.ensure_schema()
    try:
        initial = goal13.read()
        _, cycle = goal13.begin_eligibility_cycle(
            context=_context(
                revision=initial.revision,
                key="goal13-session-marker-refresh",
            )
        )
        assert cycle == 1
        _claim_goal13_eligibility_boundaries(
            goal13,
            cycle=cycle,
        )
        eligible = goal13.finish_eligibility_cycle(
            cycle_number=cycle,
            result=_goal13_eligible_result(
                candidate_updates=candidate_updates
            ),
            context=_context(
                revision=initial.revision,
                key="goal13-session-marker-refresh",
            ),
        )
        _, plan = goal13.claim_preview(
            context=_context(
                revision=eligible.revision,
                key="goal13-session-marker-execute",
                execute=True,
            )
        )
        assert plan is not None

        current_time[0] = TEST_NOW + timedelta(seconds=20)
        with pytest.raises(
            ValueError,
            match=(
                "operator_futures_hotpoint_preview_"
                "invocation_not_authorized"
            ),
        ):
            goal13.mark_preview_exchange_invoked(
                claim_id=plan.claim_id
            )

        blocked = goal13.read()
        assert blocked.preview_outcome is (
            AdminFuturesManualCallOutcome.CLAIMED
        )
        assert blocked.preview_exchange_invoked is False
        assert blocked.create_outcome is (
            AdminFuturesManualCallOutcome.NOT_RUN
        )
    finally:
        goal13.db.disconnect()


def test_preview_claim_rejects_stale_candidate_without_consuming_allowance(
    repository,
):
    initial = repository.read()
    _, cycle = repository.begin_eligibility_cycle(
        context=_context(revision=initial.revision, key="refresh-stale")
    )
    assert cycle == 1
    for category in FUTURES_MANUAL_ELIGIBILITY_CATEGORIES:
        repository.claim_eligibility_category(
            cycle_number=cycle,
            category=category,
        )
    eligible = repository.finish_eligibility_cycle(
        cycle_number=cycle,
        result=_eligible_result(
            candidate=_candidate(
                observed_at=TEST_NOW - timedelta(seconds=31)
            )
        ),
        context=_context(
            revision=initial.revision,
            key="refresh-stale",
        ),
    )

    with pytest.raises(
        ValueError,
        match="operator_futures_manual_candidate_stale",
    ):
        repository.claim_preview(
            context=_context(
                revision=eligible.revision,
                key="execute-stale",
                execute=True,
            )
        )

    unchanged = repository.read()
    assert unchanged.revision == eligible.revision
    assert (
        unchanged.preview_outcome
        is AdminFuturesManualCallOutcome.NOT_RUN
    )
    assert unchanged.client_order_id is None


def test_restart_consumes_claimed_preview_as_unknown(repository):
    eligible = _complete_eligible_cycle(repository)
    _, plan = repository.claim_preview(
        context=_context(
            revision=eligible.revision,
            key="execute-1",
            execute=True,
        )
    )
    assert plan is not None
    repository.mark_preview_exchange_invoked(claim_id=plan.claim_id)

    restarted = OperatorFuturesManualLifecycleRepository(
        _database(),
        schema=repository.schema,
        configured_portfolio_id=None,
        clock=lambda: TEST_NOW,
    )
    restarted.ensure_schema()
    try:
        restored = restarted.read()
        assert (
            restored.preview_outcome
            is AdminFuturesManualCallOutcome.UNKNOWN
        )
        assert restored.preview_exchange_invoked is True
        assert restored.create_outcome is AdminFuturesManualCallOutcome.NOT_RUN
        assert restored.diagnostic_code == (
            "operator_futures_manual_restart_preview_unknown"
        )
    finally:
        restarted.db.disconnect()


def test_restart_after_accepted_create_has_reconciliation_already_claimed(
    repository,
):
    eligible = _complete_eligible_cycle(repository)
    _, plan = repository.claim_preview(
        context=_context(
            revision=eligible.revision,
            key="execute-create-restart",
            execute=True,
        )
    )
    assert plan is not None
    repository.mark_preview_exchange_invoked(claim_id=plan.claim_id)
    repository.finish_preview(
        claim_id=plan.claim_id,
        execution=FuturesManualPreviewExecution(
            outcome=AdminFuturesManualCallOutcome.ACCEPTED,
            diagnostic_code="operator_futures_manual_preview_accepted",
            preview_id_sha256="d" * 64,
            public_evidence={},
        ),
    )
    repository.claim_create(claim_id=plan.claim_id)
    repository.mark_create_exchange_invoked(claim_id=plan.claim_id)
    repository.finish_create_and_claim_reconciliation(
        claim_id=plan.claim_id,
        execution=FuturesManualCreateExecution(
            outcome=AdminFuturesManualCallOutcome.ACCEPTED,
            diagnostic_code="operator_futures_manual_create_accepted",
            exchange_order_id_sha256="e" * 64,
            public_evidence={},
        ),
    )

    restarted = OperatorFuturesManualLifecycleRepository(
        _database(),
        schema=repository.schema,
        configured_portfolio_id=None,
        clock=lambda: TEST_NOW,
    )
    restarted.ensure_schema()
    try:
        restored = restarted.read()
        assert restored.create_outcome is AdminFuturesManualCallOutcome.ACCEPTED
        assert (
            restored.reconciliation_outcome
            is AdminFuturesManualCallOutcome.UNKNOWN
        )
        assert restored.cancel_outcome is AdminFuturesManualCallOutcome.NOT_RUN
        assert restored.diagnostic_code == (
            "operator_futures_manual_restart_reconciliation_unknown"
        )
    finally:
        restarted.db.disconnect()


def test_restart_after_nonterminal_reconciliation_has_cancel_already_claimed(
    repository,
):
    eligible = _complete_eligible_cycle(repository)
    _, plan = repository.claim_preview(
        context=_context(
            revision=eligible.revision,
            key="execute-cancel-restart",
            execute=True,
        )
    )
    assert plan is not None
    repository.mark_preview_exchange_invoked(claim_id=plan.claim_id)
    repository.finish_preview(
        claim_id=plan.claim_id,
        execution=FuturesManualPreviewExecution(
            outcome=AdminFuturesManualCallOutcome.ACCEPTED,
            diagnostic_code="operator_futures_manual_preview_accepted",
            preview_id_sha256="d" * 64,
            public_evidence={},
        ),
    )
    repository.claim_create(claim_id=plan.claim_id)
    repository.mark_create_exchange_invoked(claim_id=plan.claim_id)
    repository.finish_create_and_claim_reconciliation(
        claim_id=plan.claim_id,
        execution=FuturesManualCreateExecution(
            outcome=AdminFuturesManualCallOutcome.ACCEPTED,
            diagnostic_code="operator_futures_manual_create_accepted",
            exchange_order_id_sha256="e" * 64,
            public_evidence={},
        ),
    )
    repository.mark_reconciliation_exchange_invoked(
        claim_id=plan.claim_id
    )
    repository.finish_reconciliation_and_claim_cancel(
        claim_id=plan.claim_id,
        execution=FuturesManualReconciliationExecution(
            outcome=AdminFuturesManualCallOutcome.ACCEPTED,
            diagnostic_code=(
                "operator_futures_manual_reconciliation_accepted"
            ),
            exchange_order_id_sha256="e" * 64,
            order_status="OPEN",
            authoritatively_nonterminal=True,
            public_evidence={},
        ),
    )

    restarted = OperatorFuturesManualLifecycleRepository(
        _database(),
        schema=repository.schema,
        configured_portfolio_id=None,
        clock=lambda: TEST_NOW,
    )
    restarted.ensure_schema()
    try:
        restored = restarted.read()
        assert (
            restored.reconciliation_outcome
            is AdminFuturesManualCallOutcome.ACCEPTED
        )
        assert restored.authoritatively_nonterminal is True
        assert restored.cancel_outcome is AdminFuturesManualCallOutcome.UNKNOWN
        assert restored.diagnostic_code == (
            "operator_futures_manual_restart_cancel_unknown"
        )
    finally:
        restarted.db.disconnect()


def test_restart_consumes_partial_eligibility_cycle_without_live_claim(
    repository,
):
    initial = repository.read()
    _, cycle = repository.begin_eligibility_cycle(
        context=_context(revision=initial.revision, key="refresh-1")
    )
    assert cycle == 1
    repository.claim_eligibility_category(
        cycle_number=cycle,
        category="api_key_permissions",
    )

    restarted = OperatorFuturesManualLifecycleRepository(
        _database(),
        schema=repository.schema,
        configured_portfolio_id=None,
    )
    restarted.ensure_schema()
    try:
        restored = restarted.read()
        assert restored.active_cycle_number is None
        assert restored.cycles_used == 1
        assert (
            restored.eligibility_outcome
            is AdminFuturesManualEligibilityOutcome.UNKNOWN
        )
        assert (
            restored.preview_outcome
            is AdminFuturesManualCallOutcome.NOT_RUN
        )
        assert restored.category_attempts == {
            "api_key_permissions": 1,
            "portfolio_catalog": 0,
            "product": 0,
            "best_bid_ask": 0,
            "futures_positions": 0,
            "futures_margin_collateral": 0,
        }
    finally:
        restarted.db.disconnect()
