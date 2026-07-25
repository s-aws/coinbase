"""PostgreSQL invariants for the bounded Goal 11 position lifecycle."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
import re
from types import SimpleNamespace
import uuid

from psycopg2 import sql
import pytest

from application.admin_api.futures_public_projection import (
    opaque_futures_position_key,
)
from application.admin_api.operator_futures_position_lifecycle import (
    FUTURES_POSITION_ELIGIBILITY_CATEGORIES,
    FuturesPositionEligibilityResult,
    FuturesPositionRequestContext,
)
from core.enums import (
    AdminFuturesPositionCallOutcome,
    AdminFuturesPositionEligibilityOutcome,
)
from database.database import PostgresDB
from database.operator_futures_position_lifecycle import (
    OperatorFuturesPositionLifecycleRepository,
)


pytestmark = [pytest.mark.regression, pytest.mark.integration, pytest.mark.serial]

TEST_DB_HOST = "coinbase-test-postgres"
TEST_DB_PORT = 9876
TEST_DB_PASSWORD = os.environ.get("COINBASE_DB_PASSWORD", "postgres")
PORTFOLIO_ID = "11111111-2222-4333-8444-555555555555"
PRODUCT_ID = "AVP-20DEC30-CDE"
POSITION_KEY = opaque_futures_position_key(
    product_id=PRODUCT_ID,
    portfolio_identity=PORTFOLIO_ID,
)
TEST_NOW = datetime(2026, 7, 24, 14, 0, tzinfo=timezone.utc)
_SCHEMA_RE = re.compile(r"^test_operator_futures_position_[0-9a-f]{32}$")


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
    schema = f"test_operator_futures_position_{uuid.uuid4().hex}"
    assert _SCHEMA_RE.fullmatch(schema)
    admin = _database()
    admin.connect()
    with admin.get_cursor() as cursor:
        cursor.execute(
            sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema))
        )
    repo_db = _database()
    repo = OperatorFuturesPositionLifecycleRepository(
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
    return FuturesPositionRequestContext(
        actor_id="operator-1",
        roles=("admin", "trader"),
        expected_revision=revision,
        idempotency_key=key,
        correlation_id=f"corr-{key}",
        audit_id=str(uuid.uuid4()),
        operator_intent=(
            "authorize_one_futures_position_close_or_reduce"
            if execute
            else "refresh_one_futures_position_eligibility_cycle"
        ),
        authorize_one_no_retry_six_category_cycle=not execute,
        acknowledge_cycle_is_goal_global_and_limited_to_ten=not execute,
        acknowledge_unsuccessful_or_unknown_cycle_fails_closed=not execute,
        authorize_exact_selected_position_action=execute,
        acknowledge_action_is_mutually_exclusive_and_single_use=execute,
        acknowledge_unknown_outcome_consumes_allowance=execute,
        acknowledge_exact_order_cancel_only=execute,
    )


def _selection(
    *,
    observed_at: datetime = TEST_NOW,
    reduce_size: str = "1",
) -> dict[str, str]:
    return {
        "position_key": POSITION_KEY,
        "product_id": PRODUCT_ID,
        "position_side": "LONG",
        "close_side": "SELL",
        "current_contracts": "3",
        "full_close_size": "3",
        "bounded_reduce_size": reduce_size,
        "best_bid": "6.45",
        "best_ask": "6.47",
        "observed_at": (
            observed_at.isoformat(timespec="microseconds")
            .replace("+00:00", "Z")
        ),
    }


def _eligible_result(
    *,
    selection: dict[str, str] | None = None,
    portfolio_id: str = PORTFOLIO_ID,
) -> FuturesPositionEligibilityResult:
    exact_selection = selection or _selection()
    attempts = {
        category: 1 for category in FUTURES_POSITION_ELIGIBILITY_CATEGORIES
    }
    portfolio_hash = hashlib.sha256(portfolio_id.encode()).hexdigest()
    public = {
        "goal_id": (
            "operator_futures_position_close_reduce_and_reconciliation_v1"
        ),
        "profile_alias": "Default",
        "portfolio_id_sha256": portfolio_hash,
        "credential_can_view": True,
        "credential_can_trade": True,
        "selection": exact_selection,
        "margin_collateral_validated": True,
        "exact_position_eligible": True,
        "diagnostic_code": (
            "operator_futures_position_exact_position_eligible"
        ),
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
    ).encode()
    return FuturesPositionEligibilityResult(
        outcome=AdminFuturesPositionEligibilityOutcome.ELIGIBLE,
        diagnostic_code=(
            "operator_futures_position_exact_position_eligible"
        ),
        category_attempts=attempts,
        selection=exact_selection,
        portfolio_id_sha256=portfolio_hash,
        evidence_sha256=hashlib.sha256(encoded).hexdigest(),
        public_evidence=public,
    )


def _complete_eligible_cycle(repository):
    initial = repository.read()
    _, cycle = repository.begin_eligibility_cycle(
        context=_context(revision=initial.revision, key="refresh-1"),
        position_key=POSITION_KEY,
    )
    assert cycle == 1
    for category in FUTURES_POSITION_ELIGIBILITY_CATEGORIES:
        repository.claim_eligibility_category(
            cycle_number=cycle,
            category=category,
        )
    return repository.finish_eligibility_cycle(
        cycle_number=cycle,
        result=_eligible_result(),
        context=_context(revision=initial.revision, key="refresh-1"),
    )


def _accepted_action():
    return SimpleNamespace(
        outcome=AdminFuturesPositionCallOutcome.ACCEPTED,
        diagnostic_code="operator_futures_position_action_accepted",
        exchange_order_id_sha256=hashlib.sha256(b"exchange-1").hexdigest(),
    )


def test_initial_state_has_separate_zeroed_goal11_allowances(repository):
    initial = repository.read()

    assert initial.goal_id == (
        "operator_futures_position_close_reduce_and_reconciliation_v1"
    )
    assert initial.cycles_used == 0
    assert initial.category_attempts == {
        category: 0 for category in FUTURES_POSITION_ELIGIBILITY_CATEGORIES
    }
    assert initial.action_outcome is AdminFuturesPositionCallOutcome.NOT_RUN
    assert initial.cancel_outcome is AdminFuturesPositionCallOutcome.NOT_RUN


def test_eligible_selection_is_idempotent_and_restart_durable(repository):
    eligible = _complete_eligible_cycle(repository)

    assert eligible.eligibility_outcome is (
        AdminFuturesPositionEligibilityOutcome.ELIGIBLE
    )
    assert eligible.selection == _selection()
    assert PORTFOLIO_ID not in repr(eligible)
    replay, cycle = repository.begin_eligibility_cycle(
        context=_context(revision=0, key="refresh-1"),
        position_key=POSITION_KEY,
    )
    assert cycle is None
    assert replay == eligible

    restarted = OperatorFuturesPositionLifecycleRepository(
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


def test_refresh_idempotency_key_rejects_conflicting_position_or_revision(
    repository,
):
    initial = repository.read()
    context = _context(revision=initial.revision, key="refresh-conflict")
    repository.begin_eligibility_cycle(
        context=context,
        position_key=POSITION_KEY,
    )
    alternate_position_key = opaque_futures_position_key(
        product_id="AVP-21JAN01-CDE",
        portfolio_identity=PORTFOLIO_ID,
    )

    with pytest.raises(
        ValueError,
        match="operator_futures_position_idempotency_conflict",
    ):
        repository.begin_eligibility_cycle(
            context=context,
            position_key=alternate_position_key,
        )

    with pytest.raises(
        ValueError,
        match="operator_futures_position_idempotency_conflict",
    ):
        repository.begin_eligibility_cycle(
            context=replace(context, expected_revision=1),
            position_key=POSITION_KEY,
        )


def test_category_claim_is_append_only_and_single_use(repository):
    initial = repository.read()
    _, cycle = repository.begin_eligibility_cycle(
        context=_context(revision=initial.revision, key="refresh-1"),
        position_key=POSITION_KEY,
    )
    repository.claim_eligibility_category(
        cycle_number=cycle,
        category="api_key_permissions",
    )
    with pytest.raises(
        ValueError,
        match="operator_futures_position_category_already_claimed",
    ):
        repository.claim_eligibility_category(
            cycle_number=cycle,
            category="api_key_permissions",
        )
    with pytest.raises(
        ValueError,
        match="operator_futures_position_category_not_authorized",
    ):
        repository.claim_eligibility_category(
            cycle_number=cycle,
            category="not_authorized",
        )


@pytest.mark.parametrize(
    ("mode", "expected_size"),
    [("CLOSE_FULL", None), ("REDUCE_ONE_CONTRACT", "1")],
)
def test_action_claim_binds_one_mutually_exclusive_mode(
    repository,
    mode,
    expected_size,
):
    eligible = _complete_eligible_cycle(repository)
    claimed, plan = repository.claim_action(
        context=_context(
            revision=eligible.revision,
            key=f"execute-{mode}",
            execute=True,
        ),
        mode=mode,
    )

    assert claimed.action_outcome is AdminFuturesPositionCallOutcome.CLAIMED
    assert plan is not None
    assert plan.mode == mode
    assert plan.action_size == expected_size
    assert plan.position_key == POSITION_KEY
    assert plan.product_id == PRODUCT_ID

    replay, replay_plan = repository.claim_action(
        context=_context(
            revision=eligible.revision,
            key=f"execute-{mode}",
            execute=True,
        ),
        mode=mode,
    )
    assert replay == claimed
    assert replay_plan is None

    with pytest.raises(
        ValueError,
        match="operator_futures_position_action_already_consumed",
    ):
        repository.claim_action(
            context=_context(
                revision=claimed.revision,
                key="alternate-mode",
                execute=True,
            ),
            mode=(
                "REDUCE_ONE_CONTRACT"
                if mode == "CLOSE_FULL"
                else "CLOSE_FULL"
            ),
        )


def test_execute_idempotency_key_rejects_conflicting_mode_or_confirmation(
    repository,
):
    eligible = _complete_eligible_cycle(repository)
    context = _context(
        revision=eligible.revision,
        key="execute-conflict",
        execute=True,
    )
    repository.claim_action(
        context=context,
        mode="CLOSE_FULL",
    )

    with pytest.raises(
        ValueError,
        match="operator_futures_position_idempotency_conflict",
    ):
        repository.claim_action(
            context=context,
            mode="REDUCE_ONE_CONTRACT",
        )

    with pytest.raises(
        ValueError,
        match="operator_futures_position_idempotency_conflict",
    ):
        repository.claim_action(
            context=replace(
                context,
                acknowledge_exact_order_cancel_only=False,
            ),
            mode="CLOSE_FULL",
        )


def test_reduce_is_rejected_when_backend_has_no_bounded_reduce_size(repository):
    initial = repository.read()
    _, cycle = repository.begin_eligibility_cycle(
        context=_context(revision=initial.revision, key="refresh-1"),
        position_key=POSITION_KEY,
    )
    for category in FUTURES_POSITION_ELIGIBILITY_CATEGORIES:
        repository.claim_eligibility_category(
            cycle_number=cycle,
            category=category,
        )
    eligible = repository.finish_eligibility_cycle(
        cycle_number=cycle,
        result=_eligible_result(
            selection=_selection(reduce_size=""),
        ),
        context=_context(revision=initial.revision, key="refresh-1"),
    )

    with pytest.raises(
        ValueError,
        match="operator_futures_position_reduce_unavailable",
    ):
        repository.claim_action(
            context=_context(
                revision=eligible.revision,
                key="execute-reduce",
                execute=True,
            ),
            mode="REDUCE_ONE_CONTRACT",
        )


def test_restart_consumes_claimed_action_as_unknown_without_second_call(repository):
    eligible = _complete_eligible_cycle(repository)
    claimed, plan = repository.claim_action(
        context=_context(
            revision=eligible.revision,
            key="execute-close",
            execute=True,
        ),
        mode="CLOSE_FULL",
    )
    assert plan is not None
    repository.mark_action_exchange_invoked(claim_id=plan.claim_id)

    restarted = OperatorFuturesPositionLifecycleRepository(
        _database(),
        schema=repository.schema,
        configured_portfolio_id=None,
        clock=lambda: TEST_NOW,
    )
    restarted.ensure_schema()
    try:
        recovered = restarted.read()
        assert recovered.revision == claimed.revision + 1
        assert recovered.action_outcome is (
            AdminFuturesPositionCallOutcome.UNKNOWN
        )
        with pytest.raises(
            ValueError,
            match="operator_futures_position_action_already_consumed",
        ):
            restarted.claim_action(
                context=_context(
                    revision=recovered.revision,
                    key="second-attempt",
                    execute=True,
                ),
                mode="CLOSE_FULL",
            )
    finally:
        restarted.db.disconnect()


def test_accepted_action_claims_each_reconciliation_then_exact_cancel(repository):
    eligible = _complete_eligible_cycle(repository)
    _, plan = repository.claim_action(
        context=_context(
            revision=eligible.revision,
            key="execute-close",
            execute=True,
        ),
        mode="CLOSE_FULL",
    )
    assert plan is not None
    repository.mark_action_exchange_invoked(claim_id=plan.claim_id)
    action_record = repository.finish_action_and_claim_order_reconciliation(
        claim_id=plan.claim_id,
        execution=_accepted_action(),
    )
    assert action_record.action_outcome is (
        AdminFuturesPositionCallOutcome.ACCEPTED
    )
    assert action_record.order_reconciliation_outcome is (
        AdminFuturesPositionCallOutcome.CLAIMED
    )

    repository.mark_order_reconciliation_invoked(claim_id=plan.claim_id)
    order_record = (
        repository.finish_order_and_claim_position_reconciliation(
            claim_id=plan.claim_id,
            execution=SimpleNamespace(
                outcome=AdminFuturesPositionCallOutcome.ACCEPTED,
                diagnostic_code=(
                    "operator_futures_position_order_reconciliation_accepted"
                ),
                order_status="OPEN",
                authoritatively_nonterminal=True,
            ),
        )
    )
    assert order_record.position_reconciliation_outcome is (
        AdminFuturesPositionCallOutcome.CLAIMED
    )

    repository.mark_position_reconciliation_invoked(claim_id=plan.claim_id)
    position_record = repository.finish_position_and_claim_cancel(
        claim_id=plan.claim_id,
        execution=SimpleNamespace(
            outcome=AdminFuturesPositionCallOutcome.ACCEPTED,
            diagnostic_code=(
                "operator_futures_position_position_reconciliation_accepted"
            ),
            remaining_contracts="3",
        ),
    )
    assert position_record.cancel_outcome is (
        AdminFuturesPositionCallOutcome.CLAIMED
    )

    repository.mark_cancel_exchange_invoked(claim_id=plan.claim_id)
    complete = repository.finish_cancel(
        claim_id=plan.claim_id,
        execution=SimpleNamespace(
            outcome=AdminFuturesPositionCallOutcome.ACCEPTED,
            diagnostic_code="operator_futures_position_cancel_accepted",
        ),
    )
    assert complete.cancel_outcome is (
        AdminFuturesPositionCallOutcome.ACCEPTED
    )
    assert complete.selected_mode == "CLOSE_FULL"


def test_stale_selection_fails_before_action_claim(repository):
    initial = repository.read()
    _, cycle = repository.begin_eligibility_cycle(
        context=_context(revision=initial.revision, key="refresh-stale"),
        position_key=POSITION_KEY,
    )
    for category in FUTURES_POSITION_ELIGIBILITY_CATEGORIES:
        repository.claim_eligibility_category(
            cycle_number=cycle,
            category=category,
        )
    eligible = repository.finish_eligibility_cycle(
        cycle_number=cycle,
        result=_eligible_result(
            selection=_selection(
                observed_at=TEST_NOW - timedelta(seconds=31)
            )
        ),
        context=_context(revision=initial.revision, key="refresh-stale"),
    )

    with pytest.raises(
        ValueError,
        match="operator_futures_position_selection_stale",
    ):
        repository.claim_action(
            context=_context(
                revision=eligible.revision,
                key="execute-stale",
                execute=True,
            ),
            mode="CLOSE_FULL",
        )
