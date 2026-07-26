from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import os
import re
import uuid

from psycopg2 import sql
import pytest

from application.admin_api.operator_futures_fill_triggered_follow_up import (
    FuturesFillTriggeredControlAction,
    FuturesFillTriggeredControlState,
    FuturesFillTriggeredTriggerState,
)
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
from database.operator_futures_fill_triggered_follow_up import (
    OperatorFuturesFillTriggeredFollowUpRepository,
)
from database.operator_futures_follow_up_intent import (
    OperatorFuturesFollowUpIntentRepository,
)
from database.operator_futures_order_operations import (
    OperatorFuturesOrderOperationsRepository,
)


pytestmark = [
    pytest.mark.regression,
    pytest.mark.integration,
    pytest.mark.serial,
]

TEST_DB_HOST = "coinbase-test-postgres"
TEST_DB_PORT = 9876
TEST_DB_PASSWORD = os.environ.get("COINBASE_DB_PASSWORD", "postgres")
NOW = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)
SOURCE_ID = "00000000-0000-4000-8000-000000000551"
SECOND_SOURCE_ID = "00000000-0000-4000-8000-000000000552"
_SCHEMA_RE = re.compile(r"^test_futures_trigger_[0-9a-f]{32}$")


def _database() -> PostgresDB:
    return PostgresDB(
        host=TEST_DB_HOST,
        port=TEST_DB_PORT,
        database="postgres",
        user="postgres",
        password=TEST_DB_PASSWORD,
    )


def _private_exchange_order_id(source_client_order_id: str) -> str:
    return f"goal5-source-exchange-id-{source_client_order_id}"


def _exchange_hash(source_client_order_id: str) -> str:
    return hashlib.sha256(
        _private_exchange_order_id(source_client_order_id).encode()
    ).hexdigest()


def _order_context(
    revision: int,
    cycle: int,
    source_client_order_id: str,
):
    return FuturesOrderOperationsRequestContext(
        actor_id="operator-1",
        roles=("admin", "trader"),
        expected_revision=revision,
        idempotency_key=(
            f"goal5-{source_client_order_id}-cycle-{cycle}"
        ),
        correlation_id=(
            f"goal5-{source_client_order_id}-cycle-{cycle}"
        ),
        audit_id=str(uuid.uuid4()),
        operator_intent="reconcile_exact_futures_order",
        authorize_one_no_retry_cycle=True,
        acknowledge_cycle_is_goal_global_and_limited_to_ten=True,
        acknowledge_unknown_read_fails_closed=True,
    )


def _persist_source(
    repository: OperatorFuturesOrderOperationsRepository,
    *,
    source_client_order_id: str = SOURCE_ID,
    status: str,
    filled_size: str,
) -> None:
    initial = repository.read_goal()
    cycle_number = initial.cycles_used + 1
    context = _order_context(
        initial.revision,
        cycle_number,
        source_client_order_id,
    )
    _, cycle, replayed = repository.begin_cycle(
        context=context,
        action="RECONCILE_EXACT",
        target_client_order_id=source_client_order_id,
    )
    assert replayed is False
    assert cycle == cycle_number
    for category in FUTURES_ORDER_OPERATIONS_CATEGORIES:
        repository.claim_category(
            cycle_number=cycle, category=category
        )
    repository.claim_page(
        cycle_number=cycle,
        page_ordinal=1,
        cursor_sha256=None,
    )
    repository.mark_page_invoked(
        cycle_number=cycle, page_ordinal=1
    )
    repository.finish_page(cycle_number=cycle, page_ordinal=1)
    observation = FuturesOrderObservation(
        client_order_id=source_client_order_id,
        product_id="AVP-20DEC30-CDE",
        side="BUY",
        status=status,
        order_type="LIMIT",
        time_in_force="GOOD_UNTIL_CANCELLED",
        size="1",
        limit_price="6.90",
        filled_size=filled_size,
        created_at="2026-07-25T11:00:00+00:00",
        updated_at="2026-07-25T11:00:01+00:00",
        exchange_order_id_sha256=_exchange_hash(
            source_client_order_id
        ),
        authoritatively_nonterminal=status == "OPEN",
        cancel_eligible=status == "OPEN",
    )
    result = FuturesOrderCatalogResult(
        outcome="SUCCEEDED",
        diagnostic_code="operator_futures_orders_catalog_refreshed",
        category_attempts={
            category: 1
            for category in FUTURES_ORDER_OPERATIONS_CATEGORIES
        },
        page_count=1,
        orders=(observation,),
        credential_can_trade=True,
        portfolio_id_sha256=hashlib.sha256(b"default").hexdigest(),
        evidence_sha256=hashlib.sha256(
            (
                f"{source_client_order_id}:{status}:{filled_size}"
            ).encode()
        ).hexdigest(),
        public_evidence={},
        private_exchange_order_ids={
            source_client_order_id: _private_exchange_order_id(
                source_client_order_id
            )
        },
    )
    repository.finish_cycle(
        cycle_number=cycle,
        result=result,
        context=context,
        action="RECONCILE_EXACT",
        target_client_order_id=source_client_order_id,
    )


def _attach_intent(
    service: OperatorFuturesFollowUpIntentService,
    source_client_order_id: str,
) -> None:
    before = service.read(source_client_order_id)
    service.attach(
        context=FuturesFollowUpIntentRequestContext(
            actor_id="operator-1",
            roles=("admin", "trader"),
            idempotency_key=f"goal5-intent-{source_client_order_id}",
            correlation_id=f"goal5-intent-{source_client_order_id}",
            audit_id=str(uuid.uuid4()),
            operator_intent="attach_futures_follow_up_intent",
            reason_code="FULL_FILL_OPPOSITE_ONE_CONTRACT",
            acknowledge_future_materialization_requires_fresh_authorization=True,
            acknowledge_no_coinbase_call_or_child_creation=True,
        ),
        source_client_order_id=source_client_order_id,
        expected_source_observed_at=(
            before.eligibility.source_observed_at or ""
        ),
        expected_source_evidence_sha256=(
            before.eligibility.source_evidence_sha256 or ""
        ),
    )


@pytest.fixture
def repositories():
    schema = f"test_futures_trigger_{uuid.uuid4().hex}"
    assert _SCHEMA_RE.fullmatch(schema)
    admin = _database()
    admin.connect()
    with admin.get_cursor() as cursor:
        cursor.execute(
            sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema))
        )
    db = _database()
    order_repo = OperatorFuturesOrderOperationsRepository(
        db, schema=schema, clock=lambda: NOW
    )
    order_repo.ensure_schema()
    intent_repo = OperatorFuturesFollowUpIntentRepository(
        db, schema=schema, clock=lambda: NOW
    )
    intent_repo.ensure_schema()
    activation_repo = OperatorFuturesFillTriggeredFollowUpRepository(
        db, schema=schema, clock=lambda: NOW
    )
    activation_repo.ensure_schema()
    _persist_source(order_repo, status="OPEN", filled_size="0")
    intent_service = OperatorFuturesFollowUpIntentService(
        repository=intent_repo
    )
    _attach_intent(intent_service, SOURCE_ID)
    try:
        yield order_repo, intent_service, activation_repo
    finally:
        db.disconnect()
        with admin.get_cursor() as cursor:
            cursor.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(
                    sql.Identifier(schema)
                )
            )
        admin.disconnect()


def test_control_resume_and_exact_full_fill_claim_are_durable(
    repositories,
) -> None:
    order_repo, _intent_service, repository = repositories
    initial = repository.read(SOURCE_ID)
    assert initial.revision == 0
    assert (
        initial.control_state
        is FuturesFillTriggeredControlState.DISABLED
    )

    enabled = repository.transition_control(
        source_client_order_id=SOURCE_ID,
        action=FuturesFillTriggeredControlAction.ENABLE,
        expected_revision=0,
        authorize_one_preview_create_and_safe_closeout=True,
        acknowledge_unknown_outcome_consumes_allowance=True,
        acknowledge_child_terms_are_backend_derived=True,
        idempotency_key="goal5-enable",
        actor_id="operator-1",
        roles=("admin", "trader"),
        correlation_id="goal5-enable",
        audit_id=str(uuid.uuid4()),
    )
    assert enabled.delegated_live_authority is True
    assert repository.claim_full_fill_trigger(
        source_client_order_id=SOURCE_ID
    ) is None

    paused = repository.transition_control(
        source_client_order_id=SOURCE_ID,
        action=FuturesFillTriggeredControlAction.PAUSE,
        expected_revision=1,
        idempotency_key="goal5-pause",
        actor_id="operator-1",
        roles=("admin", "trader"),
        correlation_id="goal5-pause",
        audit_id=str(uuid.uuid4()),
    )
    replayed_enable = repository.transition_control(
        source_client_order_id=SOURCE_ID,
        action=FuturesFillTriggeredControlAction.ENABLE,
        expected_revision=0,
        authorize_one_preview_create_and_safe_closeout=True,
        acknowledge_unknown_outcome_consumes_allowance=True,
        acknowledge_child_terms_are_backend_derived=True,
        idempotency_key="goal5-enable",
        actor_id="operator-1",
        roles=("admin", "trader"),
        correlation_id="goal5-enable",
        audit_id=str(uuid.uuid4()),
    )
    assert replayed_enable == enabled
    assert repository.read(SOURCE_ID) == paused

    resumed = repository.transition_control(
        source_client_order_id=SOURCE_ID,
        action=FuturesFillTriggeredControlAction.RESUME,
        expected_revision=paused.revision,
        authorize_one_preview_create_and_safe_closeout=True,
        acknowledge_unknown_outcome_consumes_allowance=True,
        acknowledge_child_terms_are_backend_derived=True,
        idempotency_key="goal5-resume",
        actor_id="operator-1",
        roles=("admin", "trader"),
        correlation_id="goal5-resume",
        audit_id=str(uuid.uuid4()),
    )
    assert resumed.control_state is FuturesFillTriggeredControlState.ENABLED

    _persist_source(order_repo, status="FILLED", filled_size="1")
    claimed = repository.claim_full_fill_trigger(
        source_client_order_id=SOURCE_ID
    )
    assert claimed is not None
    assert (
        claimed.trigger_state
        is FuturesFillTriggeredTriggerState.CLAIMED
    )
    assert claimed.trigger_evidence_sha256 is not None
    assert repository.claim_full_fill_trigger(
        source_client_order_id=SOURCE_ID
    ) is None


def test_partial_or_schema_ambiguous_fill_never_claims(repositories) -> None:
    order_repo, _intent_service, repository = repositories
    repository.transition_control(
        source_client_order_id=SOURCE_ID,
        action=FuturesFillTriggeredControlAction.ENABLE,
        expected_revision=0,
        authorize_one_preview_create_and_safe_closeout=True,
        acknowledge_unknown_outcome_consumes_allowance=True,
        acknowledge_child_terms_are_backend_derived=True,
        idempotency_key="goal5-enable-partial",
        actor_id="operator-1",
        roles=("admin", "trader"),
        correlation_id="goal5-enable-partial",
        audit_id=str(uuid.uuid4()),
    )
    _persist_source(order_repo, status="FILLED", filled_size="0.5")
    assert repository.claim_full_fill_trigger(
        source_client_order_id=SOURCE_ID
    ) is None


def test_only_one_source_can_hold_delegated_live_authority(
    repositories,
) -> None:
    order_repo, intent_service, repository = repositories
    repository.transition_control(
        source_client_order_id=SOURCE_ID,
        action=FuturesFillTriggeredControlAction.ENABLE,
        expected_revision=0,
        authorize_one_preview_create_and_safe_closeout=True,
        acknowledge_unknown_outcome_consumes_allowance=True,
        acknowledge_child_terms_are_backend_derived=True,
        idempotency_key="goal5-enable-first-authority",
        actor_id="operator-1",
        roles=("admin", "trader"),
        correlation_id="goal5-enable-first-authority",
        audit_id=str(uuid.uuid4()),
    )
    _persist_source(
        order_repo,
        source_client_order_id=SECOND_SOURCE_ID,
        status="OPEN",
        filled_size="0",
    )
    _attach_intent(intent_service, SECOND_SOURCE_ID)

    with pytest.raises(
        ValueError,
        match=(
            "operator_futures_fill_triggered_"
            "live_authority_already_delegated"
        ),
    ):
        repository.transition_control(
            source_client_order_id=SECOND_SOURCE_ID,
            action=FuturesFillTriggeredControlAction.ENABLE,
            expected_revision=0,
            authorize_one_preview_create_and_safe_closeout=True,
            acknowledge_unknown_outcome_consumes_allowance=True,
            acknowledge_child_terms_are_backend_derived=True,
            idempotency_key="goal5-enable-second-authority",
            actor_id="operator-1",
            roles=("admin", "trader"),
            correlation_id="goal5-enable-second-authority",
            audit_id=str(uuid.uuid4()),
        )


def test_restart_after_claim_recovers_to_terminal_unknown(
    repositories,
) -> None:
    order_repo, _intent_service, repository = repositories
    repository.transition_control(
        source_client_order_id=SOURCE_ID,
        action=FuturesFillTriggeredControlAction.ENABLE,
        expected_revision=0,
        authorize_one_preview_create_and_safe_closeout=True,
        acknowledge_unknown_outcome_consumes_allowance=True,
        acknowledge_child_terms_are_backend_derived=True,
        idempotency_key="goal5-enable-restart",
        actor_id="operator-1",
        roles=("admin", "trader"),
        correlation_id="goal5-enable-restart",
        audit_id=str(uuid.uuid4()),
    )
    _persist_source(order_repo, status="FILLED", filled_size="1")
    claimed = repository.claim_full_fill_trigger(
        source_client_order_id=SOURCE_ID
    )
    assert claimed is not None

    restored = OperatorFuturesFillTriggeredFollowUpRepository(
        repository.db,
        schema=repository.schema,
        clock=lambda: NOW,
    )
    restored.ensure_schema()
    recovered = restored.read(SOURCE_ID)

    assert (
        recovered.trigger_state
        is FuturesFillTriggeredTriggerState.UNKNOWN
    )
    assert recovered.trigger_claim_id == claimed.trigger_claim_id
    assert recovered.diagnostic_code == (
        "operator_futures_fill_triggered_restart_unknown"
    )
    assert restored.claim_full_fill_trigger(
        source_client_order_id=SOURCE_ID
    ) is None


def test_terminal_finalization_is_claim_bound_and_idempotent(
    repositories,
) -> None:
    order_repo, _intent_service, repository = repositories
    repository.transition_control(
        source_client_order_id=SOURCE_ID,
        action=FuturesFillTriggeredControlAction.ENABLE,
        expected_revision=0,
        authorize_one_preview_create_and_safe_closeout=True,
        acknowledge_unknown_outcome_consumes_allowance=True,
        acknowledge_child_terms_are_backend_derived=True,
        idempotency_key="goal5-enable-terminal",
        actor_id="operator-1",
        roles=("admin", "trader"),
        correlation_id="goal5-enable-terminal",
        audit_id=str(uuid.uuid4()),
    )
    _persist_source(order_repo, status="FILLED", filled_size="1")
    claimed = repository.claim_full_fill_trigger(
        source_client_order_id=SOURCE_ID
    )
    assert claimed is not None

    terminal = repository.finalize_trigger(
        source_client_order_id=SOURCE_ID,
        trigger_claim_id=claimed.trigger_claim_id,
        trigger_state=FuturesFillTriggeredTriggerState.BLOCKED,
        lifecycle=None,
        diagnostic_code=(
            "operator_futures_fill_triggered_offline_blocked"
        ),
    )
    replayed = repository.finalize_trigger(
        source_client_order_id=SOURCE_ID,
        trigger_claim_id=claimed.trigger_claim_id,
        trigger_state=FuturesFillTriggeredTriggerState.BLOCKED,
        lifecycle=None,
        diagnostic_code=(
            "operator_futures_fill_triggered_offline_blocked"
        ),
    )

    assert terminal == replayed
    assert (
        terminal.trigger_state
        is FuturesFillTriggeredTriggerState.BLOCKED
    )
    assert terminal.lifecycle_revision == 0
    assert terminal.preview_outcome == "NOT_RUN"
    with pytest.raises(
        ValueError,
        match="operator_futures_fill_triggered_terminal_conflict",
    ):
        repository.finalize_trigger(
            source_client_order_id=SOURCE_ID,
            trigger_claim_id=claimed.trigger_claim_id,
            trigger_state=FuturesFillTriggeredTriggerState.UNKNOWN,
            lifecycle=None,
            diagnostic_code=(
                "operator_futures_fill_triggered_coordination_unknown"
            ),
        )
