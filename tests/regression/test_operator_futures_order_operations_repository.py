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
)
from database.database import PostgresDB
from database.operator_futures_order_operations import (
    OperatorFuturesOrderOperationsRepository,
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
