"""PostgreSQL invariants for the bounded Goal 10 Futures lifecycle."""

from __future__ import annotations

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
    FuturesManualEligibilityResult,
    FuturesManualRequestContext,
)
from application.admin_api.operator_futures_manual_runtime import (
    FuturesManualCancelExecution,
    FuturesManualCreateExecution,
    FuturesManualPreviewExecution,
    FuturesManualReconciliationExecution,
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


def test_initial_readback_has_exact_zeroed_category_accounting(repository):
    initial = repository.read()

    assert initial.category_attempts == {
        category: 0
        for category in FUTURES_MANUAL_ELIGIBILITY_CATEGORIES
    }
    assert initial.cycles_used == 0
    assert initial.active_cycle_number is None


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
        configured_portfolio_id=PORTFOLIO_ID,
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
