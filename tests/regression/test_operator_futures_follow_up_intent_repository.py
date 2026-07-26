from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import os
import re
import uuid

from psycopg2 import sql
import pytest

from application.admin_api.operator_futures_follow_up_intent import (
    FuturesFollowUpIntentRequestContext,
    OperatorFuturesFollowUpIntentService,
)
from application.admin_api.operator_futures_order_operations import (
    FUTURES_ORDER_OPERATIONS_CATEGORIES,
    FuturesOrderCatalogResult,
    FuturesOrderObservation,
)
from application.admin_api.operator_futures_order_operations_service import (
    FuturesOrderOperationsRequestContext,
)
from database.database import PostgresDB
from database.operator_futures_follow_up_intent import (
    OperatorFuturesFollowUpIntentRepository,
)
from database.operator_futures_order_operations import (
    OperatorFuturesOrderOperationsRepository,
)


pytestmark = [pytest.mark.regression, pytest.mark.integration, pytest.mark.serial]

TEST_DB_HOST = "coinbase-test-postgres"
TEST_DB_PORT = 9876
TEST_DB_PASSWORD = os.environ.get("COINBASE_DB_PASSWORD", "postgres")
TEST_NOW = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)
SOURCE_ID = "00000000-0000-4000-8000-000000000054"
EXCHANGE_HASH = hashlib.sha256(b"private-futures-order-id").hexdigest()
_SCHEMA_RE = re.compile(r"^test_futures_follow_up_[0-9a-f]{32}$")


def _database() -> PostgresDB:
    return PostgresDB(
        host=TEST_DB_HOST,
        port=TEST_DB_PORT,
        database="postgres",
        user="postgres",
        password=TEST_DB_PASSWORD,
    )


@pytest.fixture
def repositories():
    schema = f"test_futures_follow_up_{uuid.uuid4().hex}"
    assert _SCHEMA_RE.fullmatch(schema)
    admin = _database()
    admin.connect()
    with admin.get_cursor() as cursor:
        cursor.execute(
            sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema))
        )
    repo_db = _database()
    order_repo = OperatorFuturesOrderOperationsRepository(
        repo_db,
        schema=schema,
        clock=lambda: TEST_NOW,
    )
    order_repo.ensure_schema()
    intent_repo = OperatorFuturesFollowUpIntentRepository(
        repo_db,
        schema=schema,
        clock=lambda: TEST_NOW,
    )
    intent_repo.ensure_schema()
    _seed_open_source(order_repo)
    try:
        yield order_repo, intent_repo
    finally:
        repo_db.disconnect()
        with admin.get_cursor() as cursor:
            cursor.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(
                    sql.Identifier(schema)
                )
            )
        admin.disconnect()


def _seed_open_source(
    repository: OperatorFuturesOrderOperationsRepository,
) -> None:
    initial = repository.read_goal()
    context = FuturesOrderOperationsRequestContext(
        actor_id="operator-1",
        roles=("admin", "trader"),
        expected_revision=initial.revision,
        idempotency_key="seed-futures-follow-up-source",
        correlation_id="seed-futures-follow-up-source",
        audit_id=str(uuid.uuid4()),
        operator_intent="refresh_futures_order_catalog",
        authorize_one_no_retry_cycle=True,
        acknowledge_cycle_is_goal_global_and_limited_to_ten=True,
        acknowledge_unknown_read_fails_closed=True,
    )
    _, cycle, replayed = repository.begin_cycle(
        context=context,
        action="REFRESH_CATALOG",
        target_client_order_id=None,
    )
    assert replayed is False
    assert cycle == 1
    for category in FUTURES_ORDER_OPERATIONS_CATEGORIES:
        repository.claim_category(cycle_number=cycle, category=category)
    repository.claim_page(
        cycle_number=cycle,
        page_ordinal=1,
        cursor_sha256=None,
    )
    repository.mark_page_invoked(cycle_number=cycle, page_ordinal=1)
    repository.finish_page(cycle_number=cycle, page_ordinal=1)
    observation = FuturesOrderObservation(
        client_order_id=SOURCE_ID,
        product_id="AVP-20DEC30-CDE",
        side="BUY",
        status="OPEN",
        order_type="LIMIT",
        time_in_force="GOOD_UNTIL_CANCELLED",
        size="1",
        limit_price="6.90",
        filled_size="0",
        created_at="2026-07-25T11:00:00+00:00",
        updated_at="2026-07-25T11:00:01+00:00",
        exchange_order_id_sha256=EXCHANGE_HASH,
        authoritatively_nonterminal=True,
        cancel_eligible=True,
    )
    result = FuturesOrderCatalogResult(
        outcome="SUCCEEDED",
        diagnostic_code="operator_futures_orders_catalog_refreshed",
        category_attempts={
            category: 1 for category in FUTURES_ORDER_OPERATIONS_CATEGORIES
        },
        page_count=1,
        orders=(observation,),
        credential_can_trade=True,
        portfolio_id_sha256=hashlib.sha256(b"default").hexdigest(),
        evidence_sha256=hashlib.sha256(b"catalog").hexdigest(),
        public_evidence={},
        private_exchange_order_ids={
            SOURCE_ID: "private-futures-order-id"
        },
    )
    repository.finish_cycle(
        cycle_number=cycle,
        result=result,
        context=context,
        action="REFRESH_CATALOG",
        target_client_order_id=None,
    )


def _context(
    *,
    idempotency_key: str = "00000000-0000-4000-8000-000000000055",
    correlation_id: str = "00000000-0000-4000-8000-000000000056",
) -> FuturesFollowUpIntentRequestContext:
    return FuturesFollowUpIntentRequestContext(
        actor_id="operator-1",
        roles=("admin", "trader"),
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        audit_id=str(uuid.uuid4()),
        operator_intent="attach_futures_follow_up_intent",
        reason_code="FULL_FILL_OPPOSITE_ONE_CONTRACT",
        acknowledge_future_materialization_requires_fresh_authorization=True,
        acknowledge_no_coinbase_call_or_child_creation=True,
    )


def test_attach_is_immutable_idempotent_and_opposite_side(repositories) -> None:
    _, repository = repositories
    service = OperatorFuturesFollowUpIntentService(repository=repository)
    before = service.read(SOURCE_ID)
    assert before.eligibility.eligible is True

    attached, replayed = service.attach(
        context=_context(),
        source_client_order_id=SOURCE_ID,
        expected_source_observed_at=(
            before.eligibility.source_observed_at or ""
        ),
        expected_source_evidence_sha256=(
            before.eligibility.source_evidence_sha256 or ""
        ),
    )

    assert replayed is False
    assert attached.follow_up_intent is not None
    assert attached.follow_up_intent.root_client_order_id == SOURCE_ID
    assert attached.follow_up_intent.source_side == "BUY"
    assert attached.follow_up_intent.derived_follow_up_side == "SELL"
    assert attached.follow_up_intent.contract_count == "1"
    assert attached.coinbase_calls == 0
    assert attached.child_created is False

    replay, replayed = service.attach(
        context=_context(),
        source_client_order_id=SOURCE_ID,
        expected_source_observed_at=(
            before.eligibility.source_observed_at or ""
        ),
        expected_source_evidence_sha256=(
            before.eligibility.source_evidence_sha256 or ""
        ),
    )
    assert replayed is True
    assert replay.follow_up_intent == attached.follow_up_intent


def test_duplicate_source_with_new_identity_fails_closed(repositories) -> None:
    _, repository = repositories
    service = OperatorFuturesFollowUpIntentService(repository=repository)
    before = service.read(SOURCE_ID)
    service.attach(
        context=_context(),
        source_client_order_id=SOURCE_ID,
        expected_source_observed_at=(
            before.eligibility.source_observed_at or ""
        ),
        expected_source_evidence_sha256=(
            before.eligibility.source_evidence_sha256 or ""
        ),
    )

    with pytest.raises(
        ValueError,
        match="operator_futures_follow_up_intent_already_attached",
    ):
        service.attach(
            context=_context(
                idempotency_key=(
                    "00000000-0000-4000-8000-000000000057"
                ),
                correlation_id=(
                    "00000000-0000-4000-8000-000000000058"
                ),
            ),
            source_client_order_id=SOURCE_ID,
            expected_source_observed_at=(
                before.eligibility.source_observed_at or ""
            ),
            expected_source_evidence_sha256=(
                before.eligibility.source_evidence_sha256 or ""
            ),
        )


def test_stale_source_binding_fails_before_insert(repositories) -> None:
    _, repository = repositories
    service = OperatorFuturesFollowUpIntentService(repository=repository)
    before = service.read(SOURCE_ID)

    with pytest.raises(
        ValueError,
        match="operator_futures_follow_up_intent_source_changed",
    ):
        service.attach(
            context=_context(),
            source_client_order_id=SOURCE_ID,
            expected_source_observed_at=(
                before.eligibility.source_observed_at or ""
            ),
            expected_source_evidence_sha256="f" * 64,
        )

    assert service.read(SOURCE_ID).follow_up_intent is None


def test_intent_and_event_rows_reject_update_and_delete(repositories) -> None:
    _, repository = repositories
    service = OperatorFuturesFollowUpIntentService(repository=repository)
    before = service.read(SOURCE_ID)
    service.attach(
        context=_context(),
        source_client_order_id=SOURCE_ID,
        expected_source_observed_at=(
            before.eligibility.source_observed_at or ""
        ),
        expected_source_evidence_sha256=(
            before.eligibility.source_evidence_sha256 or ""
        ),
    )

    with pytest.raises(Exception, match="immutable"):
        with repository._cursor() as cursor:
            cursor.execute(
                f"""
                UPDATE {repository._table('operator_futures_follow_up_intent')}
                SET state = 'ATTACHED'
                WHERE source_client_order_id = %s
                """,
                (SOURCE_ID,),
            )
    with pytest.raises(Exception, match="immutable"):
        with repository._cursor() as cursor:
            cursor.execute(
                f"""
                DELETE FROM
                    {repository._table('operator_futures_follow_up_intent_event')}
                """
            )
