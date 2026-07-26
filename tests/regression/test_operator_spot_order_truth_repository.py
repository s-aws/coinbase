from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import os
from types import SimpleNamespace
import uuid

from psycopg2 import sql
import pytest

from application.admin_api.operator_spot_order_truth import (
    SPOT_ORDER_TRUTH_CATEGORIES,
    SpotOrderCatalogResult,
    SpotOrderObservation,
)
from application.admin_api.operator_spot_order_truth_service import (
    SpotOrderTruthRequestContext,
)
from database.database import PostgresDB
from database.operator_spot_order_truth import (
    OperatorSpotOrderTruthRepository,
)


pytestmark = [pytest.mark.regression, pytest.mark.integration, pytest.mark.serial]

CLIENT_ORDER_ID = "11111111-1111-4111-8111-111111111111"
EXCHANGE_HASH = hashlib.sha256(b"private-exchange-order").hexdigest()


def _database() -> PostgresDB:
    return PostgresDB(
        host="coinbase-test-postgres",
        port=9876,
        database="postgres",
        user="postgres",
        password=os.environ.get("COINBASE_DB_PASSWORD", "postgres"),
    )


@pytest.fixture
def repository():
    schema = f"test_operator_spot_truth_{uuid.uuid4().hex}"
    admin = _database()
    admin.connect()
    with admin.get_cursor() as cursor:
        cursor.execute(
            sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema))
        )
    repo_db = _database()
    repo = OperatorSpotOrderTruthRepository(repo_db, schema=schema)
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


def _context(*, revision: int, cancel: bool = False):
    return SpotOrderTruthRequestContext(
        actor_id="trader-1",
        roles=("trader",),
        expected_revision=revision,
        idempotency_key="cancel-1" if cancel else "refresh-1",
        correlation_id="cancel-correlation" if cancel else "refresh-correlation",
        audit_id=str(uuid.uuid4()),
        operator_intent=(
            "cancel_exact_spot_order" if cancel else "refresh_spot_order_truth"
        ),
        authorize_one_no_retry_cycle=not cancel,
        acknowledge_cycle_is_goal_global_and_limited_to_one=not cancel,
        acknowledge_unknown_read_fails_closed=not cancel,
        acknowledge_unknown_cancel_consumes_allowance=cancel,
    )


def _result() -> SpotOrderCatalogResult:
    order = SpotOrderObservation(
        client_order_id=CLIENT_ORDER_ID,
        product_id="BTC-USDC",
        side="BUY",
        status="OPEN",
        order_type="LIMIT",
        time_in_force="GOOD_UNTIL_CANCELLED",
        size="0.001",
        limit_price="100",
        filled_size="0",
        created_at="2026-07-26T00:00:00Z",
        updated_at="2026-07-26T00:00:01Z",
        ownership_provenance="ADMIN_MANUAL_ROOT",
        exchange_order_id_sha256=EXCHANGE_HASH,
        authoritatively_nonterminal=True,
        cancel_eligible=True,
    )
    return SpotOrderCatalogResult(
        outcome="SUCCEEDED",
        diagnostic_code="operator_spot_order_truth_catalog_refreshed",
        category_attempts={
            category: 1 for category in SPOT_ORDER_TRUTH_CATEGORIES
        },
        page_count=1,
        orders=(order,),
        credential_can_trade=True,
        portfolio_id_sha256=hashlib.sha256(b"Test").hexdigest(),
        evidence_sha256=hashlib.sha256(b"evidence").hexdigest(),
        public_evidence={
            "profile_alias": "Test",
            "portfolio_type": "CONSUMER",
            "product_type": "SPOT",
        },
    )


def test_refresh_then_exact_cancel_terminal_hash_binding(repository) -> None:
    initial = repository.read_goal()
    refresh_context = _context(revision=initial.revision)
    _, cycle_number, replayed = repository.begin_cycle(
        context=refresh_context,
        action="REFRESH_CATALOG",
        target_client_order_id=None,
    )
    assert replayed is False
    assert cycle_number == 1
    for category in SPOT_ORDER_TRUTH_CATEGORIES:
        repository.claim_category(
            cycle_number=cycle_number,
            category=category,
        )
        repository.mark_category_invoked(
            cycle_number=cycle_number,
            category=category,
        )
        repository.finish_category(
            cycle_number=cycle_number,
            category=category,
            outcome="RETURNED",
        )
    repository.claim_page(
        cycle_number=cycle_number,
        page_ordinal=1,
        cursor_sha256=None,
    )
    repository.mark_page_invoked(
        cycle_number=cycle_number,
        page_ordinal=1,
    )
    repository.finish_page(cycle_number=cycle_number, page_ordinal=1)
    refreshed = repository.finish_cycle(
        cycle_number=cycle_number,
        result=_result(),
        context=refresh_context,
        action="REFRESH_CATALOG",
        target_client_order_id=None,
    )

    with pytest.raises(
        ValueError,
        match="operator_spot_order_truth_cancel_binding_invalid",
    ):
        repository.claim_cancel(
            context=_context(revision=refreshed.revision, cancel=True),
            client_order_id="AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA",
            exchange_order_id_sha256=EXCHANGE_HASH,
        )
    cancel_context = _context(revision=refreshed.revision, cancel=True)
    claimed, claim_id, replayed = repository.claim_cancel(
        context=cancel_context,
        client_order_id=CLIENT_ORDER_ID,
        exchange_order_id_sha256=EXCHANGE_HASH,
    )
    assert claimed.cycles_used == 1
    assert replayed is False
    repository.mark_cancel_exchange_invoked(claim_id=claim_id)
    terminal = repository.finish_cancel(
        claim_id=claim_id,
        execution=SimpleNamespace(
            outcome="ACCEPTED",
            diagnostic_code="operator_spot_order_truth_cancel_accepted",
            exchange_order_id_sha256=EXCHANGE_HASH,
        ),
    )

    assert terminal.cycles_used == 1
    assert terminal.cancel_outcome == "ACCEPTED"
    assert terminal.cancel_exchange_invoked is True
    assert terminal.correlation_id == cancel_context.correlation_id
    assert terminal.audit_id == cancel_context.audit_id
    terminal_projection = repository.get_order(CLIENT_ORDER_ID)
    assert terminal_projection is not None
    assert terminal_projection["status"] == "CANCELLED"
    assert terminal_projection["authoritatively_nonterminal"] is False
    assert terminal_projection["cancel_eligible"] is False
    with pytest.raises(
        ValueError,
        match="operator_spot_order_truth_cancel_idempotency_conflict",
    ):
        repository.claim_cancel(
            context=cancel_context,
            client_order_id=CLIENT_ORDER_ID,
            exchange_order_id_sha256="f" * 64,
        )
    replay_record, replay_claim_id, replayed = repository.claim_cancel(
        context=cancel_context,
        client_order_id=CLIENT_ORDER_ID,
        exchange_order_id_sha256=EXCHANGE_HASH,
    )
    assert replayed is True
    assert replay_claim_id == claim_id
    assert replay_record == terminal
    found, resolved, durable_result = repository.read_cycle_result(
        correlation_id=cancel_context.correlation_id,
        actor_id=cancel_context.actor_id,
    )
    assert (found, resolved, durable_result) == (True, True, terminal)


def test_exact_reconcile_classifies_terminal_projection_ineligible(
    repository,
) -> None:
    initial = repository.read_goal()
    context = replace(
        _context(revision=initial.revision),
        operator_intent="reconcile_exact_spot_order",
    )
    _, cycle_number, _ = repository.begin_cycle(
        context=context,
        action="RECONCILE_EXACT",
        target_client_order_id=CLIENT_ORDER_ID,
    )
    for category in SPOT_ORDER_TRUTH_CATEGORIES:
        repository.claim_category(
            cycle_number=cycle_number,
            category=category,
        )
        repository.mark_category_invoked(
            cycle_number=cycle_number,
            category=category,
        )
        repository.finish_category(
            cycle_number=cycle_number,
            category=category,
            outcome="RETURNED",
        )
    repository.claim_page(
        cycle_number=cycle_number,
        page_ordinal=1,
        cursor_sha256=None,
    )
    repository.mark_page_invoked(
        cycle_number=cycle_number,
        page_ordinal=1,
    )
    repository.finish_page(
        cycle_number=cycle_number,
        page_ordinal=1,
    )
    terminal_order = replace(
        _result().orders[0],
        status="CANCELLED",
        authoritatively_nonterminal=False,
        cancel_eligible=False,
    )
    result = replace(_result(), orders=(terminal_order,))

    terminal = repository.finish_cycle(
        cycle_number=cycle_number,
        result=result,
        context=context,
        action="RECONCILE_EXACT",
        target_client_order_id=CLIENT_ORDER_ID,
    )

    assert terminal.last_outcome == "INELIGIBLE"
    assert (
        terminal.diagnostic_code
        == "operator_spot_order_truth_exact_order_terminal"
    )


def test_exact_reconcile_classifies_unknown_order_type_ineligible(
    repository,
) -> None:
    initial = repository.read_goal()
    context = replace(
        _context(revision=initial.revision),
        operator_intent="reconcile_exact_spot_order",
    )
    _, cycle_number, _ = repository.begin_cycle(
        context=context,
        action="RECONCILE_EXACT",
        target_client_order_id=CLIENT_ORDER_ID,
    )
    for category in SPOT_ORDER_TRUTH_CATEGORIES:
        repository.claim_category(
            cycle_number=cycle_number,
            category=category,
        )
        repository.mark_category_invoked(
            cycle_number=cycle_number,
            category=category,
        )
        repository.finish_category(
            cycle_number=cycle_number,
            category=category,
            outcome="RETURNED",
        )
    repository.claim_page(
        cycle_number=cycle_number,
        page_ordinal=1,
        cursor_sha256=None,
    )
    repository.mark_page_invoked(
        cycle_number=cycle_number,
        page_ordinal=1,
    )
    repository.finish_page(
        cycle_number=cycle_number,
        page_ordinal=1,
    )
    unknown_type = replace(
        _result().orders[0],
        order_type="UNKNOWN_ORDER_TYPE",
        cancel_eligible=False,
    )

    terminal = repository.finish_cycle(
        cycle_number=cycle_number,
        result=replace(_result(), orders=(unknown_type,)),
        context=context,
        action="RECONCILE_EXACT",
        target_client_order_id=CLIENT_ORDER_ID,
    )

    assert terminal.last_outcome == "INELIGIBLE"
    assert terminal.diagnostic_code == (
        "operator_spot_order_truth_exact_order_type_unknown"
    )
    projection = repository.get_order(CLIENT_ORDER_ID)
    assert projection is not None
    assert projection["order_type"] == "UNKNOWN_ORDER_TYPE"
    assert projection["cancel_eligible"] is False


def test_exact_reconcile_not_found_invalidates_only_target_actionability(
    repository,
) -> None:
    initial = repository.read_goal()
    context = replace(
        _context(revision=initial.revision),
        operator_intent="reconcile_exact_spot_order",
    )
    _, cycle_number, _ = repository.begin_cycle(
        context=context,
        action="RECONCILE_EXACT",
        target_client_order_id=CLIENT_ORDER_ID,
    )
    observed = _result().orders[0]
    with repository._cursor() as cursor:
        cursor.execute(
            f"""
            INSERT INTO
                {repository._table('operator_spot_order_truth_projection')} (
                    client_order_id, product_id, side, status, order_type,
                    time_in_force, size, limit_price, filled_size,
                    ownership_provenance, created_at, exchange_updated_at,
                    exchange_order_id_sha256, authoritatively_nonterminal,
                    cancel_eligible, observed_cycle_number
                )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                TRUE, TRUE, %s
            )
            """,
            (
                observed.client_order_id,
                observed.product_id,
                observed.side,
                observed.status,
                observed.order_type,
                observed.time_in_force,
                observed.size,
                observed.limit_price,
                observed.filled_size,
                observed.ownership_provenance,
                observed.created_at,
                observed.updated_at,
                observed.exchange_order_id_sha256,
                cycle_number,
            ),
        )
    for category in SPOT_ORDER_TRUTH_CATEGORIES:
        repository.claim_category(
            cycle_number=cycle_number,
            category=category,
        )
        repository.mark_category_invoked(
            cycle_number=cycle_number,
            category=category,
        )
        repository.finish_category(
            cycle_number=cycle_number,
            category=category,
            outcome="RETURNED",
        )
    repository.claim_page(
        cycle_number=cycle_number,
        page_ordinal=1,
        cursor_sha256=None,
    )
    repository.mark_page_invoked(
        cycle_number=cycle_number,
        page_ordinal=1,
    )
    repository.finish_page(
        cycle_number=cycle_number,
        page_ordinal=1,
    )

    terminal = repository.finish_cycle(
        cycle_number=cycle_number,
        result=replace(_result(), orders=()),
        context=context,
        action="RECONCILE_EXACT",
        target_client_order_id=CLIENT_ORDER_ID,
    )

    assert terminal.last_outcome == "INELIGIBLE"
    assert terminal.diagnostic_code == (
        "operator_spot_order_truth_exact_identity_not_found"
    )
    projection = repository.get_order(CLIENT_ORDER_ID)
    assert projection is not None
    assert projection["status"] == "OPEN"
    assert projection["authoritatively_nonterminal"] is False
    assert projection["cancel_eligible"] is False


def test_repository_rejects_noncanonical_reconciliation_target(repository) -> None:
    initial = repository.read_goal()

    with pytest.raises(
        ValueError,
        match="operator_spot_order_truth_identity_invalid",
    ):
        repository.begin_cycle(
            context=_context(revision=initial.revision),
            action="RECONCILE_EXACT",
            target_client_order_id="AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA",
        )

    assert repository.read_goal().cycles_used == 0


def test_restart_recovers_invoked_read_boundaries_as_unknown(repository) -> None:
    initial = repository.read_goal()
    _, cycle_number, _ = repository.begin_cycle(
        context=_context(revision=initial.revision),
        action="REFRESH_CATALOG",
        target_client_order_id=None,
    )
    repository.claim_category(
        cycle_number=cycle_number,
        category="api_key_permissions",
    )
    repository.mark_category_invoked(
        cycle_number=cycle_number,
        category="api_key_permissions",
    )
    repository.claim_category(
        cycle_number=cycle_number,
        category="portfolio_catalog",
    )
    repository.claim_page(
        cycle_number=cycle_number,
        page_ordinal=1,
        cursor_sha256=None,
    )
    repository.mark_page_invoked(
        cycle_number=cycle_number,
        page_ordinal=1,
    )
    repository.claim_page(
        cycle_number=cycle_number,
        page_ordinal=2,
        cursor_sha256=hashlib.sha256(b"cursor").hexdigest(),
    )

    restarted = OperatorSpotOrderTruthRepository(
        repository.db,
        schema=repository.schema,
    )
    restarted.ensure_schema()
    recovered = restarted.read_goal()

    assert recovered.last_outcome == "UNKNOWN"
    assert recovered.category_attempts == {
        "api_key_permissions": 1,
        "portfolio_catalog": 0,
        "spot_order_catalog": 0,
    }
    assert recovered.page_count == 1
    with restarted._cursor() as cursor:
        cursor.execute(
            f"""
            SELECT category, state, call_boundary_entered
            FROM {restarted._table('operator_spot_order_truth_category')}
            WHERE cycle_number = %s
            ORDER BY category
            """,
            (cycle_number,),
        )
        categories = cursor.fetchall()
        cursor.execute(
            f"""
            SELECT page_ordinal, state, call_boundary_entered
            FROM {restarted._table('operator_spot_order_truth_page')}
            WHERE cycle_number = %s
            ORDER BY page_ordinal
            """,
            (cycle_number,),
        )
        pages = cursor.fetchall()
    assert categories == [
        ("api_key_permissions", "UNKNOWN", True),
        ("portfolio_catalog", "PREBOUNDARY", False),
    ]
    assert pages == [
        (1, "UNKNOWN", True),
        (2, "PREBOUNDARY", False),
    ]


def test_finish_cycle_normalizes_invoked_callback_failures_as_unknown(
    repository,
) -> None:
    initial = repository.read_goal()
    context = _context(revision=initial.revision)
    _, cycle_number, _ = repository.begin_cycle(
        context=context,
        action="REFRESH_CATALOG",
        target_client_order_id=None,
    )
    for category in SPOT_ORDER_TRUTH_CATEGORIES:
        repository.claim_category(
            cycle_number=cycle_number,
            category=category,
        )
        repository.mark_category_invoked(
            cycle_number=cycle_number,
            category=category,
        )
    repository.claim_page(
        cycle_number=cycle_number,
        page_ordinal=1,
        cursor_sha256=None,
    )
    repository.mark_page_invoked(
        cycle_number=cycle_number,
        page_ordinal=1,
    )

    terminal = repository.finish_cycle(
        cycle_number=cycle_number,
        result=replace(
            _result(),
            outcome="UNKNOWN",
            diagnostic_code=(
                "operator_spot_order_truth_catalog_persistence_unknown"
            ),
            orders=(),
        ),
        context=context,
        action="REFRESH_CATALOG",
        target_client_order_id=None,
    )

    assert terminal.last_outcome == "UNKNOWN"
    with repository._cursor() as cursor:
        cursor.execute(
            f"""
            SELECT state
            FROM {repository._table('operator_spot_order_truth_category')}
            WHERE cycle_number = %s
            ORDER BY category
            """,
            (cycle_number,),
        )
        category_states = [row[0] for row in cursor.fetchall()]
        cursor.execute(
            f"""
            SELECT state
            FROM {repository._table('operator_spot_order_truth_page')}
            WHERE cycle_number = %s
            ORDER BY page_ordinal
            """,
            (cycle_number,),
        )
        page_states = [row[0] for row in cursor.fetchall()]
    assert category_states == ["UNKNOWN", "UNKNOWN", "UNKNOWN"]
    assert page_states == ["UNKNOWN"]


def test_catalog_page_boundary_is_atomic_when_page_mark_fails(repository) -> None:
    initial = repository.read_goal()
    context = _context(revision=initial.revision)
    _, cycle_number, _ = repository.begin_cycle(
        context=context,
        action="REFRESH_CATALOG",
        target_client_order_id=None,
    )
    repository.claim_category(
        cycle_number=cycle_number,
        category="spot_order_catalog",
    )

    with pytest.raises(
        ValueError,
        match="operator_spot_order_truth_page_invoke_not_claimed",
    ):
        repository.mark_catalog_page_invoked(
            cycle_number=cycle_number,
            page_ordinal=1,
        )

    with repository._cursor() as cursor:
        cursor.execute(
            f"""
            SELECT state, call_boundary_entered
            FROM {repository._table('operator_spot_order_truth_category')}
            WHERE cycle_number = %s
              AND category = 'spot_order_catalog'
            """,
            (cycle_number,),
        )
        category = cursor.fetchone()
    assert category == ("CLAIMED", False)


def test_schema_repairs_and_claim_rejects_stale_incoherent_eligibility(
    repository,
) -> None:
    initial = repository.read_goal()
    refresh_context = _context(revision=initial.revision)
    _, cycle_number, _ = repository.begin_cycle(
        context=refresh_context,
        action="REFRESH_CATALOG",
        target_client_order_id=None,
    )
    for category in SPOT_ORDER_TRUTH_CATEGORIES:
        repository.claim_category(
            cycle_number=cycle_number,
            category=category,
        )
        repository.mark_category_invoked(
            cycle_number=cycle_number,
            category=category,
        )
        repository.finish_category(
            cycle_number=cycle_number,
            category=category,
            outcome="RETURNED",
        )
    repository.claim_page(
        cycle_number=cycle_number,
        page_ordinal=1,
        cursor_sha256=None,
    )
    repository.mark_page_invoked(
        cycle_number=cycle_number,
        page_ordinal=1,
    )
    repository.finish_page(
        cycle_number=cycle_number,
        page_ordinal=1,
    )
    refreshed = repository.finish_cycle(
        cycle_number=cycle_number,
        result=_result(),
        context=refresh_context,
        action="REFRESH_CATALOG",
        target_client_order_id=None,
    )
    constraint = "operator_spot_order_truth_projection_cancel_coherent"
    with repository._cursor() as cursor:
        cursor.execute(
            f"""
            ALTER TABLE
                {repository._table('operator_spot_order_truth_projection')}
            DROP CONSTRAINT IF EXISTS {constraint}
            """
        )
        cursor.execute(
            f"""
            UPDATE
                {repository._table('operator_spot_order_truth_projection')}
            SET order_type = 'UNKNOWN_ORDER_TYPE',
                cancel_eligible = TRUE
            WHERE client_order_id = %s
            """,
            (CLIENT_ORDER_ID,),
        )

    restarted = OperatorSpotOrderTruthRepository(
        repository.db,
        schema=repository.schema,
    )
    restarted.ensure_schema()
    repaired = restarted.get_order(CLIENT_ORDER_ID)
    assert repaired is not None
    assert repaired["cancel_eligible"] is False

    with restarted._cursor() as cursor:
        cursor.execute(
            f"""
            ALTER TABLE
                {restarted._table('operator_spot_order_truth_projection')}
            DROP CONSTRAINT IF EXISTS {constraint}
            """
        )
        cursor.execute(
            f"""
            UPDATE
                {restarted._table('operator_spot_order_truth_projection')}
            SET cancel_eligible = TRUE
            WHERE client_order_id = %s
            """,
            (CLIENT_ORDER_ID,),
        )
    with pytest.raises(
        ValueError,
        match="operator_spot_order_truth_cancel_reconciliation_required",
    ):
        restarted.claim_cancel(
            context=_context(revision=refreshed.revision, cancel=True),
            client_order_id=CLIENT_ORDER_ID,
            exchange_order_id_sha256=EXCHANGE_HASH,
        )


def test_restart_after_cancel_boundary_invalidates_projection(repository) -> None:
    initial = repository.read_goal()
    refresh_context = _context(revision=initial.revision)
    _, cycle_number, _ = repository.begin_cycle(
        context=refresh_context,
        action="REFRESH_CATALOG",
        target_client_order_id=None,
    )
    for category in SPOT_ORDER_TRUTH_CATEGORIES:
        repository.claim_category(
            cycle_number=cycle_number,
            category=category,
        )
        repository.mark_category_invoked(
            cycle_number=cycle_number,
            category=category,
        )
        repository.finish_category(
            cycle_number=cycle_number,
            category=category,
            outcome="RETURNED",
        )
    repository.claim_page(
        cycle_number=cycle_number,
        page_ordinal=1,
        cursor_sha256=None,
    )
    repository.mark_page_invoked(
        cycle_number=cycle_number,
        page_ordinal=1,
    )
    repository.finish_page(
        cycle_number=cycle_number,
        page_ordinal=1,
    )
    refreshed = repository.finish_cycle(
        cycle_number=cycle_number,
        result=_result(),
        context=refresh_context,
        action="REFRESH_CATALOG",
        target_client_order_id=None,
    )
    _, claim_id, replayed = repository.claim_cancel(
        context=_context(revision=refreshed.revision, cancel=True),
        client_order_id=CLIENT_ORDER_ID,
        exchange_order_id_sha256=EXCHANGE_HASH,
    )
    assert replayed is False
    repository.mark_cancel_exchange_invoked(claim_id=claim_id)

    restarted = OperatorSpotOrderTruthRepository(
        repository.db,
        schema=repository.schema,
    )
    restarted.ensure_schema()

    recovered = restarted.read_goal()
    projection = restarted.get_order(CLIENT_ORDER_ID)
    assert recovered.cancel_outcome == "UNKNOWN"
    assert recovered.cancel_exchange_invoked is True
    assert projection is not None
    assert projection["status"] == "OPEN"
    assert projection["authoritatively_nonterminal"] is False
    assert projection["cancel_eligible"] is False


def test_final_pre_sdk_authority_failure_restores_goal12_claim(
    repository,
) -> None:
    initial = repository.read_goal()
    refresh_context = _context(revision=initial.revision)
    _, cycle_number, _ = repository.begin_cycle(
        context=refresh_context,
        action="REFRESH_CATALOG",
        target_client_order_id=None,
    )
    for category in SPOT_ORDER_TRUTH_CATEGORIES:
        repository.claim_category(
            cycle_number=cycle_number,
            category=category,
        )
        repository.mark_category_invoked(
            cycle_number=cycle_number,
            category=category,
        )
        repository.finish_category(
            cycle_number=cycle_number,
            category=category,
            outcome="RETURNED",
        )
    repository.claim_page(
        cycle_number=cycle_number,
        page_ordinal=1,
        cursor_sha256=None,
    )
    repository.mark_page_invoked(
        cycle_number=cycle_number,
        page_ordinal=1,
    )
    repository.finish_page(
        cycle_number=cycle_number,
        page_ordinal=1,
    )
    refreshed = repository.finish_cycle(
        cycle_number=cycle_number,
        result=_result(),
        context=refresh_context,
        action="REFRESH_CATALOG",
        target_client_order_id=None,
    )
    cancel_context = _context(revision=refreshed.revision, cancel=True)
    _, claim_id, replayed = repository.claim_cancel(
        context=cancel_context,
        client_order_id=CLIENT_ORDER_ID,
        exchange_order_id_sha256=EXCHANGE_HASH,
    )
    assert replayed is False
    repository.mark_cancel_exchange_invoked(claim_id=claim_id)

    restored = repository.restore_cancel_before_sdk(claim_id=claim_id)

    assert restored.cancel_outcome == "NOT_RUN"
    assert restored.cancel_exchange_invoked is None
    projection = repository.get_order(CLIENT_ORDER_ID)
    assert projection is not None
    assert projection["status"] == "OPEN"
    assert projection["authoritatively_nonterminal"] is True
    assert projection["cancel_eligible"] is True
    replay_record, replay_claim_id, replayed = repository.claim_cancel(
        context=cancel_context,
        client_order_id=CLIENT_ORDER_ID,
        exchange_order_id_sha256=EXCHANGE_HASH,
    )
    assert replayed is True
    assert replay_claim_id == claim_id
    assert replay_record == restored


def test_cancel_results_are_actor_bound_and_immutable(repository) -> None:
    initial = repository.read_goal()
    refresh_context = _context(revision=initial.revision)
    _, cycle_number, _ = repository.begin_cycle(
        context=refresh_context,
        action="REFRESH_CATALOG",
        target_client_order_id=None,
    )
    for category in SPOT_ORDER_TRUTH_CATEGORIES:
        repository.claim_category(
            cycle_number=cycle_number,
            category=category,
        )
        repository.mark_category_invoked(
            cycle_number=cycle_number,
            category=category,
        )
        repository.finish_category(
            cycle_number=cycle_number,
            category=category,
            outcome="RETURNED",
        )
    repository.claim_page(
        cycle_number=cycle_number,
        page_ordinal=1,
        cursor_sha256=None,
    )
    repository.mark_page_invoked(
        cycle_number=cycle_number,
        page_ordinal=1,
    )
    repository.finish_page(cycle_number=cycle_number, page_ordinal=1)
    refreshed = repository.finish_cycle(
        cycle_number=cycle_number,
        result=_result(),
        context=refresh_context,
        action="REFRESH_CATALOG",
        target_client_order_id=None,
    )

    first_context = _context(revision=refreshed.revision, cancel=True)
    _, first_claim, first_replayed = repository.claim_cancel(
        context=first_context,
        client_order_id=CLIENT_ORDER_ID,
        exchange_order_id_sha256=EXCHANGE_HASH,
    )
    assert first_replayed is False
    first_terminal = repository.release_cancel_before_exchange(
        claim_id=first_claim
    )
    second_context = replace(
        first_context,
        expected_revision=first_terminal.revision,
        idempotency_key="cancel-2",
        correlation_id="cancel-correlation-2",
    )
    _, second_claim, second_replayed = repository.claim_cancel(
        context=second_context,
        client_order_id=CLIENT_ORDER_ID,
        exchange_order_id_sha256=EXCHANGE_HASH,
    )
    assert second_replayed is False
    repository.mark_cancel_exchange_invoked(claim_id=second_claim)
    repository.finish_cancel(
        claim_id=second_claim,
        execution=SimpleNamespace(
            outcome="UNKNOWN",
            diagnostic_code=(
                "operator_spot_order_truth_cancel_outcome_unknown"
            ),
            exchange_order_id_sha256=EXCHANGE_HASH,
        ),
    )

    found, terminal, first_result = repository.read_cycle_result(
        correlation_id=first_context.correlation_id,
        actor_id=first_context.actor_id,
    )
    other_found, _, _ = repository.read_cycle_result(
        correlation_id=first_context.correlation_id,
        actor_id="other-actor",
    )
    assert found is True
    assert terminal is True
    assert first_result == first_terminal
    assert first_result.cancel_outcome == "NOT_RUN"
    assert other_found is False
