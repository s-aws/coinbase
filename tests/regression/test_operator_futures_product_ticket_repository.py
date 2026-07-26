from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
import os
import re
from types import SimpleNamespace
import uuid

import pytest
from psycopg2 import sql
from psycopg2.errors import ObjectNotInPrerequisiteState

from application.admin_api.operator_futures_manual_lifecycle import (
    FUTURES_MANUAL_GOAL_ID,
    FuturesManualEligibilityResult,
    FuturesManualRequestContext,
)
from application.admin_api.operator_futures_product_policy import (
    OperatorFuturesProductPolicyError,
)
from application.admin_api.operator_futures_product_ticket import (
    FUTURES_PRODUCT_TICKET_ELIGIBILITY_CATEGORIES,
    FUTURES_PRODUCT_TICKET_GOAL_ID,
    validate_futures_product_ticket_eligibility_evidence,
)
from core.enums import (
    AdminFuturesManualCallOutcome,
    AdminFuturesManualEligibilityOutcome,
)
from database.database import PostgresDB
from database.operator_futures_manual_lifecycle import (
    FuturesManualLifecycleError,
    OperatorFuturesManualLifecycleRepository,
)
from database.operator_futures_product_policy import (
    OperatorFuturesProductPolicyRepository,
)


pytestmark = [pytest.mark.regression, pytest.mark.integration, pytest.mark.serial]

TEST_DB_HOST = "coinbase-test-postgres"
TEST_DB_PORT = 9876
TEST_DB_PASSWORD = os.environ.get("COINBASE_DB_PASSWORD", "postgres")
PORTFOLIO_ID = "11111111-2222-4333-8444-555555555555"
NOW = datetime(2026, 7, 25, 21, 0, tzinfo=timezone.utc)
_SCHEMA_RE = re.compile(
    r"^test_operator_futures_product_ticket_[0-9a-f]{32}$"
)


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
    schema = f"test_operator_futures_product_ticket_{uuid.uuid4().hex}"
    assert _SCHEMA_RE.fullmatch(schema)
    admin = _database()
    admin.connect()
    with admin.get_cursor() as cursor:
        cursor.execute(
            sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema))
        )
    database = _database()
    policy = OperatorFuturesProductPolicyRepository(
        database,
        schema=schema,
    )
    policy.ensure_schema()
    lifecycle = OperatorFuturesManualLifecycleRepository(
        database,
        schema=schema,
        goal_id=FUTURES_PRODUCT_TICKET_GOAL_ID,
        configured_portfolio_id=None,
        clock=lambda: NOW,
        eligibility_evidence_validator=(
            validate_futures_product_ticket_eligibility_evidence
        ),
        claim_validator=policy.validate_selection_binding,
        client_order_id_prefix="operator-futures-product-ticket-",
    )
    lifecycle.ensure_schema()
    try:
        yield policy, lifecycle
    finally:
        database.disconnect()
        with admin.get_cursor() as cursor:
            cursor.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(
                    sql.Identifier(schema)
                )
            )
        admin.disconnect()


def _policy_command(
    policy: OperatorFuturesProductPolicyRepository,
    *,
    action: str,
    product_id: str,
    expected_revision: int,
):
    return policy.apply(
        action=action,
        product_id=product_id,
        expected_revision=expected_revision,
        actor_id="operator-1",
        roles=("admin", "trader"),
        operator_reason="exact Futures product policy transition",
        operator_intent=(
            f"{action.lower()}_exact_futures_product_for_operator_ticket"
        ),
        confirm_exact_product_policy_action=True,
        correlation_id=f"corr-{action.lower()}-{uuid.uuid4()}",
        idempotency_key=f"key-{action.lower()}-{uuid.uuid4()}",
    )


def _select_bip(policy: OperatorFuturesProductPolicyRepository):
    record = policy.read()
    record = _policy_command(
        policy,
        action="APPROVE",
        product_id="BIP-20DEC30-CDE",
        expected_revision=record.revision,
    )
    record = _policy_command(
        policy,
        action="ENABLE",
        product_id="BIP-20DEC30-CDE",
        expected_revision=record.revision,
    )
    return _policy_command(
        policy,
        action="SELECT",
        product_id="BIP-20DEC30-CDE",
        expected_revision=record.revision,
    )


def _refresh_context(revision: int) -> FuturesManualRequestContext:
    return FuturesManualRequestContext(
        actor_id="operator-1",
        roles=("admin", "trader"),
        expected_revision=revision,
        idempotency_key=f"refresh-{uuid.uuid4()}",
        correlation_id=f"corr-refresh-{uuid.uuid4()}",
        audit_id=str(uuid.uuid4()),
        operator_intent=(
            "refresh_one_futures_product_ticket_eligibility_cycle"
        ),
        authorize_one_no_retry_six_category_cycle=True,
        acknowledge_cycle_is_goal_global_and_limited_to_ten=True,
        acknowledge_unsuccessful_or_unknown_cycle_fails_closed=True,
    )


def _execute_context(revision: int) -> FuturesManualRequestContext:
    return FuturesManualRequestContext(
        actor_id="operator-1",
        roles=("admin", "trader"),
        expected_revision=revision,
        idempotency_key=f"execute-{uuid.uuid4()}",
        correlation_id=f"corr-execute-{uuid.uuid4()}",
        audit_id=str(uuid.uuid4()),
        operator_intent=(
            "preview_submit_and_safe_closeout_one_futures_product_ticket"
        ),
        authorize_preview_create_and_safe_closeout=True,
        acknowledge_unknown_outcome_consumes_allowance=True,
        acknowledge_create_requires_accepted_identical_preview=True,
        acknowledge_cancel_is_only_for_exact_nonterminal_child=True,
    )


def _eligible_result(policy) -> FuturesManualEligibilityResult:
    selection = policy.selection
    candidate = {
        "product_id": selection.product_id,
        "side": "BUY",
        "order_type": "LIMIT_GTC",
        "post_only": "true",
        "contract_count": "1",
        "limit_price": "498",
        "contract_size": "0.1",
        "opening_reference_notional_usdc": "50.10",
        "maximum_exposure_reference_notional_usdc": "50.10",
        "buffered_close_reference_notional_usdc": "60.12",
        "branch_turnover_reference_notional_usdc": "110.22",
        "opening_cap_usdc": "100",
        "exposure_cap_usdc": "150",
        "turnover_cap_usdc": "300",
        "product_policy_revision": str(selection.policy_revision),
        "product_policy_sha256": selection.policy_sha256,
        "observed_at": NOW.isoformat(),
    }
    portfolio_hash = hashlib.sha256(
        PORTFOLIO_ID.encode("utf-8")
    ).hexdigest()
    attempts = {
        category: 1
        for category in FUTURES_PRODUCT_TICKET_ELIGIBILITY_CATEGORIES
    }
    public = {
        "goal_id": FUTURES_PRODUCT_TICKET_GOAL_ID,
        "profile_alias": "Default",
        "portfolio_type": "DEFAULT",
        "portfolio_id_sha256": portfolio_hash,
        "credential_can_view": True,
        "credential_can_trade": True,
        "selection_authority": (
            "backend_enabled_futures_product_policy"
        ),
        "product_id": selection.product_id,
        "contract_count": "1",
        "product_policy_revision": selection.policy_revision,
        "product_policy_sha256": selection.policy_sha256,
        "caps": {
            "opening_usdc": "100",
            "exposure_usdc": "150",
            "turnover_usdc": "300",
            "comparison": "strictly_less_than",
        },
        "candidate": candidate,
        "exact_v3_eligible": True,
        "diagnostic_code": "operator_futures_product_ticket_eligible",
        "category_attempts": attempts,
        "raw_responses_included": False,
        "private_identifiers_included": False,
        "exception_text_included": False,
    }
    evidence_hash = hashlib.sha256(
        json.dumps(
            public,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()
    return FuturesManualEligibilityResult(
        outcome=AdminFuturesManualEligibilityOutcome.ELIGIBLE,
        diagnostic_code="operator_futures_product_ticket_eligible",
        category_attempts=attempts,
        candidate=candidate,
        portfolio_id_sha256=portfolio_hash,
        evidence_sha256=evidence_hash,
        public_evidence=public,
    )


def _complete_cycle(policy, lifecycle):
    initial = lifecycle.read()
    context = _refresh_context(initial.revision)
    _, cycle_number = lifecycle.begin_eligibility_cycle(
        context=context
    )
    assert cycle_number == 1
    for category in FUTURES_PRODUCT_TICKET_ELIGIBILITY_CATEGORIES:
        lifecycle.claim_eligibility_category(
            cycle_number=cycle_number,
            category=category,
        )
    return lifecycle.finish_eligibility_cycle(
        cycle_number=cycle_number,
        result=_eligible_result(policy),
        context=context,
    )


def test_policy_change_atomically_invalidates_ticket_candidate(
    repositories,
) -> None:
    policy, lifecycle = repositories
    selected = _select_bip(policy)
    eligible = _complete_cycle(selected, lifecycle)
    assert eligible.eligibility_outcome is (
        AdminFuturesManualEligibilityOutcome.ELIGIBLE
    )

    _policy_command(
        policy,
        action="DISABLE",
        product_id="BIP-20DEC30-CDE",
        expected_revision=selected.revision,
    )

    invalidated = lifecycle.read()
    assert invalidated.eligibility_outcome is None
    assert invalidated.candidate is None
    assert invalidated.diagnostic_code == (
        "operator_futures_product_ticket_policy_changed"
    )


def test_claim_binds_exact_current_policy_and_policy_freezes_after_claim(
    repositories,
) -> None:
    policy, lifecycle = repositories
    selected = _select_bip(policy)
    eligible = _complete_cycle(selected, lifecycle)

    claimed, plan = lifecycle.claim_preview(
        context=_execute_context(eligible.revision)
    )

    assert plan is not None
    assert plan.client_order_id.startswith(
        "operator-futures-product-ticket-"
    )
    assert claimed.preview_outcome.value == "CLAIMED"

    with pytest.raises(
        OperatorFuturesProductPolicyError,
        match="operator_futures_product_policy_goal_terminal",
    ):
        _policy_command(
            policy,
            action="DISABLE",
            product_id="BIP-20DEC30-CDE",
            expected_revision=selected.revision,
        )


def test_product_ticket_executor_diagnostics_persist_across_exact_call_chain(
    repositories,
) -> None:
    policy, lifecycle = repositories
    selected = _select_bip(policy)
    eligible = _complete_cycle(selected, lifecycle)
    _, plan = lifecycle.claim_preview(
        context=_execute_context(eligible.revision)
    )
    assert plan is not None

    lifecycle.mark_preview_exchange_invoked(claim_id=plan.claim_id)
    preview = lifecycle.finish_preview(
        claim_id=plan.claim_id,
        execution=SimpleNamespace(
            outcome=AdminFuturesManualCallOutcome.ACCEPTED,
            diagnostic_code=(
                "operator_futures_product_ticket_preview_accepted"
            ),
            preview_id_sha256="a" * 64,
        ),
    )
    assert preview.diagnostic_code == (
        "operator_futures_product_ticket_preview_accepted"
    )

    lifecycle.claim_create(claim_id=plan.claim_id)
    lifecycle.mark_create_exchange_invoked(claim_id=plan.claim_id)
    created = lifecycle.finish_create(
        claim_id=plan.claim_id,
        execution=SimpleNamespace(
            outcome=AdminFuturesManualCallOutcome.ACCEPTED,
            diagnostic_code=(
                "operator_futures_product_ticket_create_accepted"
            ),
            exchange_order_id_sha256="b" * 64,
        ),
    )
    assert created.diagnostic_code == (
        "operator_futures_product_ticket_create_accepted"
    )

    lifecycle.claim_reconciliation(claim_id=plan.claim_id)
    lifecycle.mark_reconciliation_exchange_invoked(
        claim_id=plan.claim_id
    )
    reconciled = lifecycle.finish_reconciliation(
        claim_id=plan.claim_id,
        execution=SimpleNamespace(
            outcome=AdminFuturesManualCallOutcome.ACCEPTED,
            diagnostic_code=(
                "operator_futures_product_ticket_reconciliation_accepted"
            ),
            order_status="OPEN",
            authoritatively_nonterminal=True,
        ),
    )
    assert reconciled.diagnostic_code == (
        "operator_futures_product_ticket_reconciliation_accepted"
    )

    lifecycle.claim_cancel(claim_id=plan.claim_id)
    lifecycle.mark_cancel_exchange_invoked(claim_id=plan.claim_id)
    cancelled = lifecycle.finish_cancel(
        claim_id=plan.claim_id,
        execution=SimpleNamespace(
            outcome=AdminFuturesManualCallOutcome.ACCEPTED,
            diagnostic_code=(
                "operator_futures_product_ticket_cancel_accepted"
            ),
        ),
    )
    assert cancelled.diagnostic_code == (
        "operator_futures_product_ticket_cancel_accepted"
    )


def test_refresh_idempotency_is_request_bound_and_never_replays_later_state(
    repositories,
) -> None:
    policy, lifecycle = repositories
    selected = _select_bip(policy)
    initial = lifecycle.read()
    context = _refresh_context(initial.revision)

    claimed, cycle_number = lifecycle.begin_eligibility_cycle(
        context=context
    )
    assert cycle_number == 1
    replayed, replayed_cycle = lifecycle.begin_eligibility_cycle(
        context=context
    )
    assert replayed == claimed
    assert replayed_cycle is None

    with pytest.raises(
        FuturesManualLifecycleError,
        match="operator_futures_manual_idempotency_conflict",
    ):
        lifecycle.begin_eligibility_cycle(
            context=replace(
                context,
                actor_id="operator-2",
                correlation_id="corr-rebound-refresh",
            )
        )

    for category in FUTURES_PRODUCT_TICKET_ELIGIBILITY_CATEGORIES:
        lifecycle.claim_eligibility_category(
            cycle_number=cycle_number,
            category=category,
        )
    completed = lifecycle.finish_eligibility_cycle(
        cycle_number=cycle_number,
        result=_eligible_result(selected),
        context=context,
    )
    next_context = _refresh_context(completed.revision)
    _, next_cycle = lifecycle.begin_eligibility_cycle(
        context=next_context
    )
    assert next_cycle == 2

    replayed_completed, replayed_cycle = (
        lifecycle.begin_eligibility_cycle(
            context=replace(
                context,
                audit_id=str(uuid.uuid4()),
            )
        )
    )
    assert replayed_completed == completed
    assert replayed_cycle is None


def test_execute_idempotency_is_bound_to_exact_operator_confirmations(
    repositories,
) -> None:
    policy, lifecycle = repositories
    selected = _select_bip(policy)
    eligible = _complete_cycle(selected, lifecycle)
    context = _execute_context(eligible.revision)

    claimed, plan = lifecycle.claim_preview(context=context)
    assert plan is not None
    replayed, replayed_plan = lifecycle.claim_preview(context=context)
    assert replayed == claimed
    assert replayed_plan is None

    with pytest.raises(
        FuturesManualLifecycleError,
        match="operator_futures_manual_idempotency_conflict",
    ):
        lifecycle.claim_preview(
            context=replace(
                context,
                acknowledge_cancel_is_only_for_exact_nonterminal_child=False,
            )
        )


def test_idempotency_keys_are_scoped_to_the_exact_goal(repositories) -> None:
    _policy, lifecycle = repositories
    other = OperatorFuturesManualLifecycleRepository(
        lifecycle.db,
        schema=lifecycle.schema,
        goal_id=FUTURES_MANUAL_GOAL_ID,
        configured_portfolio_id=None,
        clock=lambda: NOW,
    )
    other.ensure_schema()
    shared = _refresh_context(lifecycle.read().revision)

    _, first_cycle = lifecycle.begin_eligibility_cycle(context=shared)
    _, other_cycle = other.begin_eligibility_cycle(context=shared)

    assert first_cycle == 1
    assert other_cycle == 1


@pytest.mark.parametrize("operation", ["UPDATE", "DELETE"])
def test_completed_refresh_result_snapshot_is_database_append_only(
    repositories,
    operation: str,
) -> None:
    policy, lifecycle = repositories
    selected = _select_bip(policy)
    _complete_cycle(selected, lifecycle)
    qualified_table = sql.SQL("{}.{}").format(
        sql.Identifier(lifecycle.schema),
        sql.Identifier("operator_futures_manual_command_result"),
    )

    with pytest.raises(
        ObjectNotInPrerequisiteState,
        match="operator_futures_manual_evidence_append_only",
    ):
        with lifecycle.db.get_cursor() as cursor:
            if operation == "UPDATE":
                cursor.execute(
                    sql.SQL(
                        "UPDATE {} SET result_revision = result_revision"
                    ).format(qualified_table)
                )
            else:
                cursor.execute(
                    sql.SQL("DELETE FROM {}").format(qualified_table)
                )
