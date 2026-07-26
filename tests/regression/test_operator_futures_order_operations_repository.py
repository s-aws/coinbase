from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import os
import re
from types import SimpleNamespace
import uuid

from psycopg2 import sql
import pytest

from application.admin_api.operator_futures_order_operations import (
    FUTURES_ORDER_OPERATIONS_CATEGORIES,
    FuturesOrderCatalogResult,
    FuturesOrderObservation,
)
from application.admin_api.operator_futures_order_operations_service import (
    FuturesOrderOperationsRequestContext,
    OperatorFuturesOrderOperationsService,
)
from application.admin_api.operator_futures_manual_lifecycle import (
    FuturesManualLifecycleError,
)
from application.admin_api.operator_hotpoint_control import (
    FUTURES_HOTPOINT_GOAL_ID,
)
from application.admin_api.operator_futures_position_lifecycle import (
    FUTURES_POSITION_GOAL_ID,
    FuturesPositionLifecycleError,
    OperatorFuturesPositionLifecycleService,
)
from core.enums import AdminFuturesPositionCallOutcome
from database.database import PostgresDB
from database.operator_futures_manual_lifecycle import (
    OperatorFuturesManualLifecycleRepository,
)
from database.operator_futures_order_operations import (
    OperatorFuturesOrderOperationsRepository,
)
from database.operator_futures_position_lifecycle import (
    OperatorFuturesPositionLifecycleRepository,
)


pytestmark = [pytest.mark.regression, pytest.mark.integration, pytest.mark.serial]

TEST_DB_HOST = "coinbase-test-postgres"
TEST_DB_PORT = 9876
TEST_DB_PASSWORD = os.environ.get("COINBASE_DB_PASSWORD", "postgres")
TEST_NOW = datetime(2026, 7, 25, 9, 0, tzinfo=timezone.utc)
CLIENT_ORDER_ID = "operator-futures-order-001"
EXCHANGE_HASH = hashlib.sha256(b"private-exchange-order-001").hexdigest()
_SCHEMA_RE = re.compile(r"^test_operator_futures_orders_[0-9a-f]{32}$")


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
    schema = f"test_operator_futures_orders_{uuid.uuid4().hex}"
    assert _SCHEMA_RE.fullmatch(schema)
    admin = _database()
    admin.connect()
    with admin.get_cursor() as cursor:
        cursor.execute(
            sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema))
        )
    repo_db = _database()
    repo = OperatorFuturesOrderOperationsRepository(
        repo_db,
        schema=schema,
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


def _context(
    *,
    revision: int,
    key: str,
    action: str,
    actor_id: str = "operator-1",
    roles: tuple[str, ...] = ("admin", "trader"),
    correlation_id: str | None = None,
):
    return FuturesOrderOperationsRequestContext(
        actor_id=actor_id,
        roles=roles,
        expected_revision=revision,
        idempotency_key=key,
        correlation_id=correlation_id or f"corr-{key}",
        audit_id=str(uuid.uuid4()),
        operator_intent={
            "REFRESH_CATALOG": "refresh_futures_order_catalog",
            "RECONCILE_EXACT": "reconcile_exact_futures_order",
            "CANCEL_EXACT": "cancel_exact_futures_order",
        }[action],
        authorize_one_no_retry_cycle=True,
        acknowledge_cycle_is_goal_global_and_limited_to_ten=True,
        acknowledge_unknown_read_fails_closed=True,
        acknowledge_unknown_cancel_consumes_allowance=(
            action == "CANCEL_EXACT"
        ),
    )


def _result() -> FuturesOrderCatalogResult:
    observation = FuturesOrderObservation(
        client_order_id=CLIENT_ORDER_ID,
        product_id="AVP-20DEC30-CDE",
        side="BUY",
        status="OPEN",
        order_type="LIMIT",
        time_in_force="GOOD_UNTIL_CANCELLED",
        size="1",
        limit_price="6.90",
        filled_size="0",
        created_at="2026-07-25T08:00:00Z",
        updated_at="2026-07-25T08:00:01Z",
        exchange_order_id_sha256=EXCHANGE_HASH,
        authoritatively_nonterminal=True,
        cancel_eligible=True,
    )
    attempts = {
        category: 1 for category in FUTURES_ORDER_OPERATIONS_CATEGORIES
    }
    return FuturesOrderCatalogResult(
        outcome="SUCCEEDED",
        diagnostic_code="operator_futures_orders_catalog_refreshed",
        category_attempts=attempts,
        page_count=1,
        orders=(observation,),
        credential_can_trade=True,
        portfolio_id_sha256=hashlib.sha256(b"default-portfolio").hexdigest(),
        evidence_sha256=hashlib.sha256(b"catalog-evidence").hexdigest(),
        public_evidence={
            "goal_id": (
                "operator_futures_order_inventory_detail_cancel_reconcile_v1"
            ),
            "raw_responses_included": False,
            "private_identifiers_included": False,
            "exception_text_included": False,
        },
        private_exchange_order_ids={
            CLIENT_ORDER_ID: "private-exchange-order-001"
        },
    )


def _complete_cycle(
    repository,
    *,
    action: str = "REFRESH_CATALOG",
    key: str | None = None,
    correlation_id: str | None = None,
    result: FuturesOrderCatalogResult | None = None,
):
    initial = repository.read_goal()
    context = _context(
        revision=initial.revision,
        key=key or f"{action}-1",
        action=action,
        correlation_id=correlation_id,
    )
    _, cycle, replayed = repository.begin_cycle(
        context=context,
        action=action,
        target_client_order_id=(
            CLIENT_ORDER_ID if action != "REFRESH_CATALOG" else None
        ),
    )
    assert replayed is False
    assert cycle == initial.cycles_used + 1
    for category in FUTURES_ORDER_OPERATIONS_CATEGORIES:
        repository.claim_category(
            cycle_number=cycle,
            category=category,
        )
    repository.claim_page(
        cycle_number=cycle,
        page_ordinal=1,
        cursor_sha256=None,
    )
    repository.mark_page_invoked(cycle_number=cycle, page_ordinal=1)
    repository.finish_page(cycle_number=cycle, page_ordinal=1)
    return repository.finish_cycle(
        cycle_number=cycle,
        result=result or _result(),
        context=context,
        action=action,
        target_client_order_id=(
            CLIENT_ORDER_ID if action != "REFRESH_CATALOG" else None
        ),
    )


def test_catalog_projection_is_durable_filterable_and_private_id_free(repository):
    initial = repository.read_goal()
    assert initial.cycles_used == 0
    assert initial.cancel_outcome == "NOT_RUN"

    completed = _complete_cycle(repository)

    assert completed.cycles_used == 1
    page = repository.list_orders(
        product_id="AVP-20DEC30-CDE",
        order_status="OPEN",
        limit=25,
        offset=0,
    )
    assert page["pagination"]["total_matching_count"] == 1
    assert page["items"][0]["client_order_id"] == CLIENT_ORDER_ID
    assert page["items"][0]["exchange_order_id_sha256"] == EXCHANGE_HASH
    assert "private-exchange-order-001" not in repr(page)
    detail = repository.get_order(CLIENT_ORDER_ID)
    assert detail is not None
    assert detail["authoritatively_nonterminal"] is True


def test_successful_refresh_revokes_authority_from_absent_durable_projection(
    repository,
):
    catalog = _result()
    second_client_order_id = "operator-futures-order-002"
    second_observation = replace(
        catalog.orders[0],
        client_order_id=second_client_order_id,
        exchange_order_id_sha256=hashlib.sha256(
            b"private-exchange-order-002"
        ).hexdigest(),
    )
    first_catalog = replace(
        catalog,
        orders=(catalog.orders[0], second_observation),
        private_exchange_order_ids={
            **catalog.private_exchange_order_ids,
            second_client_order_id: "private-exchange-order-002",
        },
    )
    _complete_cycle(repository, key="REFRESH_CATALOG-1", result=first_catalog)

    stale_before = repository.get_order(second_client_order_id)
    assert stale_before is not None
    assert stale_before["authoritatively_nonterminal"] is True
    assert stale_before["cancel_eligible"] is True

    _complete_cycle(repository, key="REFRESH_CATALOG-2", result=catalog)

    current = repository.get_order(CLIENT_ORDER_ID)
    stale = repository.get_order(second_client_order_id)
    assert current is not None
    assert current["authoritatively_nonterminal"] is True
    assert current["cancel_eligible"] is True
    assert stale is not None
    assert stale["status"] == "OPEN"
    assert stale["authoritatively_nonterminal"] is False
    assert stale["cancel_eligible"] is False


def test_unknown_order_status_is_durable_and_cancel_fails_unknown(repository):
    catalog = _result()
    unknown_observation = replace(
        catalog.orders[0],
        status="UNKNOWN_ORDER_STATUS",
        authoritatively_nonterminal=False,
        cancel_eligible=False,
    )

    completed = _complete_cycle(
        repository,
        action="CANCEL_EXACT",
        result=replace(catalog, orders=(unknown_observation,)),
    )

    assert completed.last_outcome == "UNKNOWN"
    assert completed.diagnostic_code == (
        "operator_futures_order_exact_order_status_unknown"
    )
    assert completed.cancel_outcome == "NOT_RUN"
    assert completed.cancel_exchange_invoked is None
    detail = repository.get_order(CLIENT_ORDER_ID)
    assert detail is not None
    assert detail["client_order_id"] == CLIENT_ORDER_ID
    assert detail["status"] == "UNKNOWN_ORDER_STATUS"
    assert detail["authoritatively_nonterminal"] is False
    assert detail["cancel_eligible"] is False


def test_unknown_order_type_is_durable_and_cancel_stays_unclaimed(repository):
    catalog = _result()
    degraded_observation = replace(
        catalog.orders[0],
        order_type="UNKNOWN_ORDER_TYPE",
        cancel_eligible=False,
    )

    completed = _complete_cycle(
        repository,
        action="CANCEL_EXACT",
        result=replace(catalog, orders=(degraded_observation,)),
    )

    assert completed.last_outcome == "INELIGIBLE"
    assert completed.diagnostic_code == (
        "operator_futures_order_exact_order_type_unknown"
    )
    assert completed.cancel_outcome == "NOT_RUN"
    assert completed.cancel_exchange_invoked is None
    detail = repository.get_order(CLIENT_ORDER_ID)
    assert detail is not None
    assert detail["status"] == "OPEN"
    assert detail["order_type"] == "UNKNOWN_ORDER_TYPE"
    assert detail["cancel_eligible"] is False


def test_schema_upgrade_adds_cancel_eligibility_to_existing_projection(repository):
    with repository._cursor() as cursor:
        cursor.execute(
            f"""
            ALTER TABLE
                {repository._table('operator_futures_order_projection')}
            DROP COLUMN cancel_eligible
            """
        )
    upgraded = OperatorFuturesOrderOperationsRepository(
        repository.db,
        schema=repository.schema,
        clock=lambda: TEST_NOW,
    )

    upgraded.ensure_schema()

    with repository._cursor() as cursor:
        cursor.execute(
            """
            SELECT is_nullable, column_default
            FROM information_schema.columns
            WHERE table_schema = %s
              AND table_name = 'operator_futures_order_projection'
              AND column_name = 'cancel_eligible'
            """,
            (repository.schema,),
        )
        column = cursor.fetchone()
    assert column is not None
    assert column[0] == "NO"


def test_cancel_claim_is_single_use_and_unknown_consumes_after_boundary(repository):
    completed = _complete_cycle(repository, action="CANCEL_EXACT")
    context = _context(
        revision=completed.revision,
        key="CANCEL_EXACT-1",
        action="CANCEL_EXACT",
    )

    claimed, claim_id = repository.claim_cancel(
        context=context,
        client_order_id=CLIENT_ORDER_ID,
        exchange_order_id_sha256=EXCHANGE_HASH,
    )
    assert claimed.cancel_outcome == "CLAIMED"
    repository.mark_cancel_exchange_invoked(claim_id=claim_id)

    recovered = OperatorFuturesOrderOperationsRepository(
        repository.db,
        schema=repository.schema,
        clock=lambda: TEST_NOW,
    )
    recovered.ensure_schema()
    state = recovered.read_goal()

    assert state.cancel_outcome == "UNKNOWN"
    assert state.cancel_exchange_invoked is True
    assert state.diagnostic_code == (
        "operator_futures_order_cancel_restart_unknown"
    )
    with pytest.raises(
        ValueError,
        match="operator_futures_order_cancel_allowance_consumed",
    ):
        recovered.claim_cancel(
            context=_context(
                revision=state.revision,
                key="CANCEL_EXACT-2",
                action="CANCEL_EXACT",
            ),
            client_order_id=CLIENT_ORDER_ID,
            exchange_order_id_sha256=EXCHANGE_HASH,
        )


def test_cancel_claim_can_be_released_only_before_exchange_boundary(repository):
    completed = _complete_cycle(repository, action="CANCEL_EXACT")
    context = _context(
        revision=completed.revision,
        key="CANCEL_EXACT-1",
        action="CANCEL_EXACT",
    )
    _, claim_id = repository.claim_cancel(
        context=context,
        client_order_id=CLIENT_ORDER_ID,
        exchange_order_id_sha256=EXCHANGE_HASH,
    )

    released = repository.release_cancel_before_exchange(
        claim_id=claim_id,
    )

    assert released.cancel_outcome == "NOT_RUN"
    assert released.cancel_exchange_invoked is None
    assert released.cancel_target_client_order_id is None
    assert released.cancel_exchange_order_id_sha256 is None


def test_cancel_claim_restart_before_exchange_restores_contract_shape(repository):
    completed = _complete_cycle(repository, action="CANCEL_EXACT")
    context = _context(
        revision=completed.revision,
        key="CANCEL_EXACT-1",
        action="CANCEL_EXACT",
    )
    repository.claim_cancel(
        context=context,
        client_order_id=CLIENT_ORDER_ID,
        exchange_order_id_sha256=EXCHANGE_HASH,
    )

    recovered = OperatorFuturesOrderOperationsRepository(
        repository.db,
        schema=repository.schema,
        clock=lambda: TEST_NOW,
    )
    recovered.ensure_schema()
    state = recovered.read_goal()

    assert state.cancel_outcome == "NOT_RUN"
    assert state.cancel_exchange_invoked is None
    assert state.cancel_target_client_order_id is None
    assert state.cancel_exchange_order_id_sha256 is None
    assert state.diagnostic_code == (
        "operator_futures_order_cancel_interrupted_before_call"
    )


def test_cycle_replay_is_actor_role_bound_and_returns_original_result(repository):
    initial = repository.read_goal()
    first_context = _context(
        revision=initial.revision,
        key="refresh-original",
        action="REFRESH_CATALOG",
    )
    first = _complete_cycle(repository, key="refresh-original")
    second = _complete_cycle(repository, action="RECONCILE_EXACT")
    assert second.last_action == "RECONCILE_EXACT"

    replay, cycle_number, replayed = repository.begin_cycle(
        context=first_context,
        action="REFRESH_CATALOG",
        target_client_order_id=None,
    )

    assert replayed is True
    assert cycle_number is None
    assert replay.revision == first.revision
    assert replay.cycles_used == 1
    assert replay.last_action == "REFRESH_CATALOG"
    assert replay.last_target_client_order_id is None

    for conflict in (
        _context(
            revision=initial.revision,
            key="refresh-original",
            action="REFRESH_CATALOG",
            actor_id="operator-2",
        ),
        _context(
            revision=initial.revision,
            key="refresh-original",
            action="REFRESH_CATALOG",
            roles=("admin",),
        ),
        _context(
            revision=initial.revision,
            key="refresh-original",
            action="REFRESH_CATALOG",
            correlation_id="corr-other-request",
        ),
    ):
        with pytest.raises(
            ValueError,
            match="operator_futures_orders_idempotency_conflict",
        ):
            repository.begin_cycle(
                context=conflict,
                action="REFRESH_CATALOG",
                target_client_order_id=None,
            )


def test_terminal_request_result_is_actor_bound_and_survives_later_cycles(
    repository,
):
    first = _complete_cycle(repository, key="refresh-original")
    second = _complete_cycle(repository, action="RECONCILE_EXACT")
    assert second.revision > first.revision

    found, terminal, result = repository.read_cycle_result(
        correlation_id="corr-refresh-original",
        actor_id="operator-1",
    )
    other_found, other_terminal, other_result = (
        repository.read_cycle_result(
            correlation_id="corr-refresh-original",
            actor_id="operator-2",
        )
    )

    assert found is True
    assert terminal is True
    assert result == first
    assert other_found is False
    assert other_terminal is False
    assert other_result is None


def test_pending_cancel_transition_is_exposed_as_active_readback(repository):
    completed = _complete_cycle(repository, action="CANCEL_EXACT")

    readback = repository.read_goal()

    assert completed.active_cycle_number is None
    assert completed.last_outcome == "SUCCEEDED"
    assert readback.active_cycle_number == 1
    assert readback.last_outcome == "CLAIMED"
    assert readback.diagnostic_code == (
        "operator_futures_order_cancel_transition_pending"
    )


def test_distinct_idempotency_keys_cannot_reuse_a_correlation(repository):
    shared_correlation = "corr-shared-request"
    _complete_cycle(
        repository,
        key="refresh-first",
        correlation_id=shared_correlation,
    )
    current = repository.read_goal()

    with pytest.raises(
        ValueError,
        match="operator_futures_orders_correlation_conflict",
    ):
        repository.begin_cycle(
            context=_context(
                revision=current.revision,
                key="refresh-second",
                action="REFRESH_CATALOG",
                correlation_id=shared_correlation,
            ),
            action="REFRESH_CATALOG",
            target_client_order_id=None,
        )

def test_cancel_replay_remains_pending_until_write_once_terminal_result(repository):
    initial = repository.read_goal()
    key = "cancel-terminal-replay"
    completed = _complete_cycle(
        repository,
        action="CANCEL_EXACT",
        key=key,
    )
    replay_context = _context(
        revision=initial.revision,
        key=key,
        action="CANCEL_EXACT",
    )

    with pytest.raises(
        ValueError,
        match="operator_futures_orders_idempotency_replay_pending",
    ):
        repository.begin_cycle(
            context=replay_context,
            action="CANCEL_EXACT",
            target_client_order_id=CLIENT_ORDER_ID,
        )

    claimed, claim_id = repository.claim_cancel(
        context=_context(
            revision=completed.revision,
            key=key,
            action="CANCEL_EXACT",
        ),
        client_order_id=CLIENT_ORDER_ID,
        exchange_order_id_sha256=EXCHANGE_HASH,
    )
    assert claimed.cancel_outcome == "CLAIMED"
    repository.mark_cancel_exchange_invoked(claim_id=claim_id)

    with pytest.raises(
        ValueError,
        match="operator_futures_orders_idempotency_replay_pending",
    ):
        repository.begin_cycle(
            context=replay_context,
            action="CANCEL_EXACT",
            target_client_order_id=CLIENT_ORDER_ID,
        )

    terminal = repository.finish_cancel(
        claim_id=claim_id,
        execution=SimpleNamespace(
            outcome="ACCEPTED",
            diagnostic_code="operator_futures_order_cancel_accepted",
            exchange_order_id_sha256=EXCHANGE_HASH,
        ),
    )
    replay, cycle_number, replayed = repository.begin_cycle(
        context=replay_context,
        action="CANCEL_EXACT",
        target_client_order_id=CLIENT_ORDER_ID,
    )

    assert replayed is True
    assert cycle_number is None
    assert replay == terminal
    with repository._cursor() as cursor:
        cursor.execute(
            f"""
            SELECT result_json, cancel_cycle_number
            FROM {repository._table('operator_futures_order_operations_cycle')}
            LEFT JOIN
                {repository._table('operator_futures_order_operations_goal')}
                ON goal_id = %s
            WHERE cycle_number = 1
            """,
            (
                "operator_futures_order_inventory_detail_cancel_reconcile_v1",
            ),
        )
        stored = cursor.fetchone()
    assert stored[0]["cancel_outcome"] == "ACCEPTED"
    assert stored[1] == 1


def test_cancel_claim_fences_new_cycles_and_keeps_original_cycle_binding(repository):
    completed = _complete_cycle(repository, action="CANCEL_EXACT")
    _, claim_id = repository.claim_cancel(
        context=_context(
            revision=completed.revision,
            key="CANCEL_EXACT-1",
            action="CANCEL_EXACT",
        ),
        client_order_id=CLIENT_ORDER_ID,
        exchange_order_id_sha256=EXCHANGE_HASH,
    )
    claimed = repository.read_goal()

    with pytest.raises(
        ValueError,
        match="operator_futures_order_cancel_active",
    ):
        repository.begin_cycle(
            context=_context(
                revision=claimed.revision,
                key="refresh-during-cancel",
                action="REFRESH_CATALOG",
            ),
            action="REFRESH_CATALOG",
            target_client_order_id=None,
        )

    repository.mark_cancel_exchange_invoked(claim_id=claim_id)
    repository.finish_cancel(
        claim_id=claim_id,
        execution=SimpleNamespace(
            outcome="REJECTED",
            diagnostic_code=(
                "operator_futures_order_cancel_exchange_rejected"
            ),
            exchange_order_id_sha256=EXCHANGE_HASH,
        ),
    )
    state = repository.read_goal()
    assert state.cycles_used == 1


def test_restart_between_cancel_cycle_and_claim_records_proven_pre_call_result(
    repository,
):
    initial = repository.read_goal()
    key = "cancel-pre-claim-restart"
    _complete_cycle(repository, action="CANCEL_EXACT", key=key)

    recovered = OperatorFuturesOrderOperationsRepository(
        repository.db,
        schema=repository.schema,
        clock=lambda: TEST_NOW,
    )
    recovered.ensure_schema()
    state = recovered.read_goal()
    replay, cycle_number, replayed = recovered.begin_cycle(
        context=_context(
            revision=initial.revision,
            key=key,
            action="CANCEL_EXACT",
        ),
        action="CANCEL_EXACT",
        target_client_order_id=CLIENT_ORDER_ID,
    )

    assert state.cancel_outcome == "NOT_RUN"
    assert state.cancel_exchange_invoked is None
    assert state.diagnostic_code == (
        "operator_futures_order_cancel_interrupted_before_claim"
    )
    assert replayed is True
    assert cycle_number is None
    assert replay == state


def test_cancel_finishes_with_sanitized_terminal_evidence(repository):
    completed = _complete_cycle(repository, action="CANCEL_EXACT")
    context = _context(
        revision=completed.revision,
        key="CANCEL_EXACT-1",
        action="CANCEL_EXACT",
    )
    _, claim_id = repository.claim_cancel(
        context=context,
        client_order_id=CLIENT_ORDER_ID,
        exchange_order_id_sha256=EXCHANGE_HASH,
    )
    repository.mark_cancel_exchange_invoked(claim_id=claim_id)

    terminal = repository.finish_cancel(
        claim_id=claim_id,
        execution=SimpleNamespace(
            outcome="ACCEPTED",
            diagnostic_code="operator_futures_order_cancel_accepted",
            exchange_order_id_sha256=EXCHANGE_HASH,
        ),
    )

    assert terminal.cancel_outcome == "ACCEPTED"
    assert terminal.cancel_exchange_invoked is True
    assert terminal.cancel_target_client_order_id == CLIENT_ORDER_ID


@pytest.mark.parametrize("winner", ("orders_detail", "hotpoint_v2"))
def test_exact_child_cancel_invocation_has_one_shared_cross_workspace_winner(
    repository,
    winner,
):
    portfolio_id = "11111111-2222-4333-8444-555555555555"
    portfolio_hash = hashlib.sha256(portfolio_id.encode()).hexdigest()
    completed = _complete_cycle(
        repository,
        action="CANCEL_EXACT",
        result=replace(
            _result(),
            portfolio_id_sha256=portfolio_hash,
        ),
    )
    _, orders_claim_id = repository.claim_cancel(
        context=_context(
            revision=completed.revision,
            key="CANCEL_EXACT-1",
            action="CANCEL_EXACT",
        ),
        client_order_id=CLIENT_ORDER_ID,
        exchange_order_id_sha256=EXCHANGE_HASH,
    )
    goal13 = OperatorFuturesManualLifecycleRepository(
        repository.db,
        schema=repository.schema,
        configured_portfolio_id=(
            portfolio_id
        ),
        clock=lambda: TEST_NOW,
        goal_id=FUTURES_HOTPOINT_GOAL_ID,
        eligibility_evidence_validator=lambda _result: None,
        claim_validator=lambda **_kwargs: None,
        preview_invocation_validator=lambda **_kwargs: None,
        create_invocation_validator=lambda **_kwargs: None,
        client_order_id_prefix="operator-futures-hotpoint-v2-",
    )
    goal13.ensure_schema()
    goal13_claim_id = str(uuid.uuid4())
    goal13_child_id = CLIENT_ORDER_ID
    with repository._cursor() as cursor:
        cursor.execute(
            f"""
            UPDATE {goal13._table('operator_futures_manual_goal')}
               SET execution_claim_id = %s,
                   client_order_id = %s,
                   preview_outcome = 'ACCEPTED',
                   preview_exchange_invoked = TRUE,
                   create_outcome = 'ACCEPTED',
                   create_exchange_invoked = TRUE,
                   exchange_order_id_sha256 = %s,
                   reconciliation_outcome = 'ACCEPTED',
                   reconciliation_exchange_invoked = TRUE,
                   order_status = 'OPEN',
                   authoritatively_nonterminal = TRUE,
                   cancel_outcome = 'CLAIMED',
                   cancel_exchange_invoked = FALSE
             WHERE goal_id = %s
            """,
            (
                goal13_claim_id,
                goal13_child_id,
                EXCHANGE_HASH,
                FUTURES_HOTPOINT_GOAL_ID,
            ),
        )

    if winner == "orders_detail":
        repository.mark_cancel_exchange_invoked(
            claim_id=orders_claim_id
        )
        with pytest.raises(
            FuturesManualLifecycleError,
            match=(
                "operator_futures_cancel_invocation_already_sealed"
            ),
        ):
            goal13.mark_cancel_exchange_invoked(
                claim_id=goal13_claim_id
            )
        goal13.release_cancel_invocation_conflict(
            claim_id=goal13_claim_id
        )
    else:
        goal13.mark_cancel_exchange_invoked(
            claim_id=goal13_claim_id
        )
        with pytest.raises(
            ValueError,
            match=(
                "operator_futures_cancel_invocation_already_sealed"
            ),
        ):
            repository.mark_cancel_exchange_invoked(
                claim_id=orders_claim_id
            )
        repository.release_cancel_before_exchange(
            claim_id=orders_claim_id,
            diagnostic_code=(
                "operator_futures_cancel_invocation_already_sealed"
            ),
        )

    orders_state = repository.read_goal()
    goal13_state = goal13.read()
    assert (
        orders_state.cancel_exchange_invoked is True
    ) is (winner == "orders_detail")
    assert (
        goal13_state.cancel_exchange_invoked is True
    ) is (winner == "hotpoint_v2")
    loser_state = (
        goal13_state
        if winner == "orders_detail"
        else orders_state
    )
    assert str(loser_state.cancel_outcome) in {
        "NOT_RUN",
        "AdminFuturesManualCallOutcome.NOT_RUN",
    }
    assert loser_state.diagnostic_code == (
        "operator_futures_cancel_invocation_already_sealed"
    )
    with repository._cursor() as cursor:
        cursor.execute(
            f"""
            SELECT owner_ledger, claim_id, portfolio_id_sha256,
                   client_order_id, mutation_class,
                   exchange_order_id_sha256
              FROM {repository._table(
                  'operator_futures_cancel_invocation_seal'
              )}
             WHERE client_order_id = %s
            """,
            (CLIENT_ORDER_ID,),
        )
        seal = cursor.fetchone()
    assert seal is not None
    assert seal[0] == (
        "ORDER_OPERATIONS"
        if winner == "orders_detail"
        else FUTURES_HOTPOINT_GOAL_ID
    )
    assert str(seal[1]) == (
        orders_claim_id
        if winner == "orders_detail"
        else goal13_claim_id
    )
    assert seal[2:] == (
        portfolio_hash,
        CLIENT_ORDER_ID,
        "CANCEL",
        EXCHANGE_HASH,
    )
    assert repository.get_order(CLIENT_ORDER_ID)["cancel_eligible"] is False
    assert goal13.is_cancel_invocation_sealed() is True
    orders_service = OperatorFuturesOrderOperationsService(
        repository=repository,
        catalog_reader=SimpleNamespace(),
        exchange_executor=SimpleNamespace(),
    )
    assert (
        orders_service.get_order(CLIENT_ORDER_ID)["cancel_eligible"]
        is False
    )


@pytest.mark.parametrize("winner", ("orders_detail", "position"))
def test_position_and_orders_cancel_share_one_invocation_and_restart_truthfully(
    repository,
    winner,
):
    portfolio_id = "11111111-2222-4333-8444-555555555555"
    portfolio_hash = hashlib.sha256(portfolio_id.encode()).hexdigest()
    completed = _complete_cycle(
        repository,
        action="CANCEL_EXACT",
        result=replace(
            _result(),
            portfolio_id_sha256=portfolio_hash,
        ),
    )
    _, orders_claim_id = repository.claim_cancel(
        context=_context(
            revision=completed.revision,
            key="CANCEL_EXACT-1",
            action="CANCEL_EXACT",
        ),
        client_order_id=CLIENT_ORDER_ID,
        exchange_order_id_sha256=EXCHANGE_HASH,
    )
    position = OperatorFuturesPositionLifecycleRepository(
        repository.db,
        schema=repository.schema,
        configured_portfolio_id=portfolio_id,
        clock=lambda: TEST_NOW,
    )
    position.ensure_schema()
    position_claim_id = str(uuid.uuid4())
    with repository._cursor() as cursor:
        cursor.execute(
            f"""
            UPDATE {position._table('operator_futures_position_goal')}
               SET portfolio_id_sha256 = %s,
                   execution_claim_id = %s,
                   selected_mode = 'CLOSE_FULL',
                   client_order_id = %s,
                   action_outcome = 'ACCEPTED',
                   action_exchange_invoked = TRUE,
                   exchange_order_id_sha256 = %s,
                   order_reconciliation_outcome = 'ACCEPTED',
                   order_reconciliation_exchange_invoked = TRUE,
                   order_status = 'OPEN',
                   authoritatively_nonterminal = TRUE,
                   position_reconciliation_outcome = 'ACCEPTED',
                   position_reconciliation_exchange_invoked = TRUE,
                   remaining_contracts = '3',
                   cancel_outcome = 'CLAIMED',
                   cancel_exchange_invoked = FALSE
             WHERE goal_id = %s
            """,
            (
                portfolio_hash,
                position_claim_id,
                CLIENT_ORDER_ID,
                EXCHANGE_HASH,
                FUTURES_POSITION_GOAL_ID,
            ),
        )
    sdk_calls: list[str] = []

    def invoke(name, marker):
        marker()
        sdk_calls.append(name)

    if winner == "orders_detail":
        invoke(
            "orders_detail",
            lambda: repository.mark_cancel_exchange_invoked(
                claim_id=orders_claim_id
            ),
        )
        with pytest.raises(
            FuturesPositionLifecycleError,
            match="operator_futures_cancel_invocation_already_sealed",
        ):
            invoke(
                "position",
                lambda: position.mark_cancel_exchange_invoked(
                    claim_id=position_claim_id
                ),
            )
        released = position.release_cancel_invocation_conflict(
            claim_id=position_claim_id
        )
        restarted = OperatorFuturesPositionLifecycleRepository(
            repository.db,
            schema=repository.schema,
            configured_portfolio_id=portfolio_id,
            clock=lambda: TEST_NOW,
        )
        restarted.ensure_schema()
        recovered = restarted.read()
    else:
        invoke(
            "position",
            lambda: position.mark_cancel_exchange_invoked(
                claim_id=position_claim_id
            ),
        )
        with pytest.raises(
            ValueError,
            match="operator_futures_cancel_invocation_already_sealed",
        ):
            invoke(
                "orders_detail",
                lambda: repository.mark_cancel_exchange_invoked(
                    claim_id=orders_claim_id
                ),
            )
        released = repository.release_cancel_before_exchange(
            claim_id=orders_claim_id,
            diagnostic_code=(
                "operator_futures_cancel_invocation_already_sealed"
            ),
        )
        restarted = OperatorFuturesOrderOperationsRepository(
            repository.db,
            schema=repository.schema,
            clock=lambda: TEST_NOW,
        )
        restarted.ensure_schema()
        recovered = restarted.read_goal()

    assert sdk_calls == [winner]
    assert str(released.cancel_outcome) in {
        "NOT_RUN",
        "AdminFuturesPositionCallOutcome.NOT_RUN",
    }
    assert released.cancel_exchange_invoked is None
    assert released.diagnostic_code == (
        "operator_futures_cancel_invocation_already_sealed"
    )
    assert str(recovered.cancel_outcome) in {
        "NOT_RUN",
        "AdminFuturesPositionCallOutcome.NOT_RUN",
    }
    assert recovered.cancel_exchange_invoked is None
    assert recovered.diagnostic_code == (
        "operator_futures_cancel_invocation_already_sealed"
    )
    assert repository.get_order(CLIENT_ORDER_ID)["cancel_eligible"] is False
    assert position.is_cancel_invocation_sealed() is True
    orders_service = OperatorFuturesOrderOperationsService(
        repository=repository,
        catalog_reader=SimpleNamespace(),
        exchange_executor=SimpleNamespace(),
    )
    assert (
        orders_service.get_order(CLIENT_ORDER_ID)["cancel_eligible"]
        is False
    )
    position_service = OperatorFuturesPositionLifecycleService(
        repository=position,
        eligibility_reader_factory=lambda _position_key: None,
        exchange_executor=SimpleNamespace(),
    )
    position_readback = position_service.read()
    if winner == "orders_detail":
        assert (
            position_readback.cancel_outcome
            is AdminFuturesPositionCallOutcome.NOT_RUN
        )
        assert position_readback.cancel_exchange_invoked is None
        assert position_readback.diagnostic_code == (
            "operator_futures_cancel_invocation_already_sealed"
        )
