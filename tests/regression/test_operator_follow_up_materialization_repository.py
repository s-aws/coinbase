"""PostgreSQL invariants for operator-authorized follow-up materialization.

The tests reuse the isolated random-schema harness from the attachment store.
They never address the operator database and never import or invoke Coinbase.
"""

from __future__ import annotations

from decimal import Decimal
import hashlib
import json
import uuid

import psycopg2
import pytest

from core.enums import (
    FollowUpMaterializationState,
    FollowUpMaterializedChildTransitionKind,
)
from database.order_follow_up_intent import (
    FollowUpIntentStoreConflict,
    FollowUpMaterializationCommand,
    OperatorFollowUpIntentRepository,
    derive_operator_follow_up_materialization_child_id,
)
from tests.regression.test_admin_api_order_follow_up_intent_repository import (
    KNOWN_PRODUCT_ID,
    PORTFOLIO_ID,
    _RepositoryHarness,
    _command,
    _insert_chain,
    _insert_order,
    repository_harness,
)


pytestmark = [pytest.mark.regression, pytest.mark.integration, pytest.mark.serial]


def _attach_then_fill(
    harness: _RepositoryHarness,
    *,
    fill_quantity: Decimal = Decimal("1"),
) -> tuple[OperatorFollowUpIntentRepository, str, str, str]:
    root_id, source_id = _insert_chain(harness)
    repository = harness.repository()
    attached = repository.attach(_command(source_id))
    harness.execute(
        f'UPDATE "{harness.schema}".order_parent '
        "SET status = 'FILLED' WHERE client_order_id = %s",
        (source_id,),
    )
    harness.execute(
        f"""
        INSERT INTO "{harness.schema}".fill_ledger (
            derived_trade_key, instrument, side, quantity, price,
            client_order_id
        ) VALUES (%s, %s, 'BUY', %s, 100, %s)
        """,
        (str(uuid.uuid4()), KNOWN_PRODUCT_ID, fill_quantity, source_id),
    )
    return repository, root_id, source_id, attached.record.follow_up_intent_id


def _materialization_command(
    *,
    source_id: str,
    root_id: str,
    intent_id: str,
    idempotency_key: str | None = None,
    payload_seed: str = "same-materialization-payload",
    product_id: str = KNOWN_PRODUCT_ID,
    child_side: str = "SELL",
    base_size: Decimal = Decimal("1"),
    limit_price: Decimal = Decimal("101"),
    portfolio_id: str = PORTFOLIO_ID,
) -> FollowUpMaterializationCommand:
    return FollowUpMaterializationCommand(
        source_client_order_id=source_id,
        root_client_order_id=root_id,
        follow_up_intent_id=intent_id,
        actor_id="operator-test-001",
        roles=("trader",),
        environment="local",
        idempotency_key=idempotency_key or f"materialize-{uuid.uuid4()}",
        correlation_id=f"corr-{uuid.uuid4()}",
        operator_intent="authorize_and_materialize_follow_up_intent",
        audit_id=str(uuid.uuid4()),
        payload_sha256=hashlib.sha256(payload_seed.encode("ascii")).hexdigest(),
        product_id=product_id,
        child_side=child_side,
        base_size=base_size,
        limit_price=limit_price,
        portfolio_id=portfolio_id,
    )


def _insert_planned_child(
    harness: _RepositoryHarness,
    *,
    child_id: str,
    root_id: str,
    side: str = "SELL",
    size: Decimal = Decimal("1"),
    price: Decimal = Decimal("101"),
) -> None:
    harness.execute(
        f"""
        INSERT INTO "{harness.schema}".order_parent (
            client_order_id, product_id, side, size, price, status,
            parent_order_id, ownership_provenance, retail_portfolio_id
        ) VALUES (%s, %s, %s, %s, %s, 'PENDING', %s,
                  'ADMIN_FILL_FOLLOW_UP', %s)
        """,
        (child_id, KNOWN_PRODUCT_ID, side, size, price, root_id, PORTFOLIO_ID),
    )


def _operation_authority(
    operation_idempotency_key: str,
    *,
    actor_id: str = "operator-closeout-001",
    correlation_id: str = "corr-safe-closeout-001",
    operator_intent: str = "authorize_safe_closeout",
) -> dict[str, object]:
    return {
        "operation_idempotency_key": operation_idempotency_key,
        "actor_id": actor_id,
        "roles": ("trader",),
        "environment": "local",
        "operator_intent": operator_intent,
        "correlation_id": correlation_id,
    }


def _persist_quarantined_stealth_child(
    harness: _RepositoryHarness,
    *,
    materialization_id: str,
    child_id: str,
    root_id: str,
) -> None:
    harness.execute(
        f"""
        CREATE TABLE IF NOT EXISTS "{harness.schema}".stealth_orders (
            id BIGSERIAL PRIMARY KEY,
            stealth_order_id UUID UNIQUE NOT NULL,
            parent_order_id UUID,
            product_id VARCHAR(32) NOT NULL,
            side VARCHAR(10) NOT NULL,
            total_size NUMERIC NOT NULL,
            remaining_size NUMERIC NOT NULL,
            revealed_size NUMERIC NOT NULL DEFAULT 0,
            executed_size NUMERIC NOT NULL DEFAULT 0,
            limit_price NUMERIC NOT NULL,
            status VARCHAR(32) NOT NULL,
            reveal_condition_json JSONB NOT NULL,
            anchor_repricing_state_json JSONB NOT NULL,
            revealed_orders JSONB NOT NULL DEFAULT '[]'::jsonb,
            last_placement_at TIMESTAMPTZ,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    _insert_planned_child(
        harness,
        child_id=child_id,
        root_id=root_id,
    )
    materialization_hash = hashlib.sha256(
        materialization_id.encode("utf-8")
    ).hexdigest()
    harness.execute(
        f"""
        INSERT INTO "{harness.schema}".stealth_orders (
            stealth_order_id, parent_order_id, product_id, side,
            total_size, remaining_size, limit_price, status,
            reveal_condition_json, anchor_repricing_state_json
        ) VALUES (%s, %s, %s, 'SELL', 1, 0, 101, 'HIDDEN',
                  %s::jsonb, %s::jsonb)
        """,
        (
            child_id,
            root_id,
            KNOWN_PRODUCT_ID,
            json.dumps(
                {
                    "operator_materialization_quarantine": True,
                    "materialization_binding_sha256": materialization_hash,
                }
            ),
            json.dumps(
                {
                    "operator_materialization_quarantine": True,
                    "materialization_binding_sha256": materialization_hash,
                }
            ),
        ),
    )


def _row_mapping(
    harness: _RepositoryHarness,
    query: str,
    params: tuple = (),
) -> dict[str, object]:
    with harness.database.get_cursor() as cursor:
        cursor.execute(query, params)
        row = cursor.fetchone()
        assert row is not None
        return dict(zip((item[0] for item in cursor.description), row))


def test_passive_materialization_read_never_initializes_schema(
    repository_harness: _RepositoryHarness,
    monkeypatch: pytest.MonkeyPatch,
):
    repository, _root_id, source_id, _intent_id = _attach_then_fill(
        repository_harness
    )
    repository._schema_ready = False

    def fail_if_called() -> None:
        raise AssertionError("passive read attempted DDL")

    monkeypatch.setattr(repository, "ensure_schema", fail_if_called)

    readback = repository.read_materialization(source_id)

    assert readback.readiness.eligible is True
    assert readback.attempt is None


def test_filled_attached_intent_is_locally_ready_with_deterministic_child(
    repository_harness: _RepositoryHarness,
):
    repository, root_id, source_id, intent_id = _attach_then_fill(
        repository_harness
    )

    readback = repository.read_materialization(source_id)

    assert readback.readiness.eligible is True
    assert readback.readiness.blockers == ()
    assert readback.readiness.follow_up_intent_id == intent_id
    assert readback.readiness.source_status == "FILLED"
    assert readback.readiness.full_fill_consistent is True
    assert readback.readiness.deterministic_child_client_order_id == (
        derive_operator_follow_up_materialization_child_id(
            root_client_order_id=root_id,
            source_client_order_id=source_id,
        )
    )


@pytest.mark.parametrize(
    ("mutation", "blocker"),
    [
        ("partial_ledger", "source_full_fill_inconsistent"),
        ("open_status", "source_status_not_filled"),
        ("conflicting_snapshot", "source_full_fill_inconsistent"),
        ("active_claim", "follow_up_semantic_claim_present"),
    ],
)
def test_materialization_readiness_fails_closed_on_stale_or_conflicting_evidence(
    repository_harness: _RepositoryHarness,
    mutation: str,
    blocker: str,
):
    quantity = Decimal("0.5") if mutation == "partial_ledger" else Decimal("1")
    repository, _root_id, source_id, _intent_id = _attach_then_fill(
        repository_harness,
        fill_quantity=quantity,
    )
    if mutation == "open_status":
        repository_harness.execute(
            f'UPDATE "{repository_harness.schema}".order_parent '
            "SET status = 'OPEN' WHERE client_order_id = %s",
            (source_id,),
        )
    elif mutation == "conflicting_snapshot":
        repository_harness.execute(
            f"""
            INSERT INTO "{repository_harness.schema}".order_match_audit (
                client_order_id, cumulative_quantity,
                derived_size_delta, number_of_fills
            ) VALUES (%s, 0.5, 0.5, 1)
            """,
            (source_id,),
        )
    elif mutation == "active_claim":
        repository_harness.execute(
            f"""
            INSERT INTO "{repository_harness.schema}".order_follow_up_semantic_claim (
                claim_id, source_client_order_id, claim_kind, trigger, state
            ) VALUES (%s, %s, 'AUTOMATIC_FILLED', 'FILLED', 'CLAIMED')
            """,
            (str(uuid.uuid4()), source_id),
        )

    readiness = repository.read_materialization(source_id).readiness

    assert readiness.eligible is False
    assert blocker in readiness.blockers


def test_prepare_is_exactly_once_and_same_key_replays(
    repository_harness: _RepositoryHarness,
):
    repository, root_id, source_id, intent_id = _attach_then_fill(
        repository_harness
    )
    command = _materialization_command(
        source_id=source_id,
        root_id=root_id,
        intent_id=intent_id,
        idempotency_key="one-materialization-key",
    )

    first = repository.prepare_materialization(command)
    replay = repository.prepare_materialization(command)

    assert first.replayed is False
    assert replay.replayed is True
    assert replay.attempt.materialization_id == first.attempt.materialization_id
    assert first.attempt.current_state == (
        FollowUpMaterializationState.KNOWN_NOT_INVOKED.value
    )
    assert first.attempt.child_client_order_id == (
        derive_operator_follow_up_materialization_child_id(
            root_client_order_id=root_id,
            source_client_order_id=source_id,
        )
    )
    assert repository_harness.scalar(
        f'SELECT COUNT(*) FROM "{repository_harness.schema}".'
        "operator_follow_up_materialization_attempt"
    ) == 1
    assert repository_harness.scalar(
        f'SELECT COUNT(*) FROM "{repository_harness.schema}".'
        "operator_follow_up_materialization_event"
    ) == 1


def test_prepare_rejects_same_key_payload_drift_and_second_source_claim(
    repository_harness: _RepositoryHarness,
):
    repository, root_id, source_id, intent_id = _attach_then_fill(
        repository_harness
    )
    first = _materialization_command(
        source_id=source_id,
        root_id=root_id,
        intent_id=intent_id,
        idempotency_key="materialization-key",
    )
    repository.prepare_materialization(first)

    with pytest.raises(FollowUpIntentStoreConflict) as drift:
        repository.prepare_materialization(
            _materialization_command(
                source_id=source_id,
                root_id=root_id,
                intent_id=intent_id,
                idempotency_key="materialization-key",
                payload_seed="changed",
            )
        )
    with pytest.raises(FollowUpIntentStoreConflict) as duplicate:
        repository.prepare_materialization(
            _materialization_command(
                source_id=source_id,
                root_id=root_id,
                intent_id=intent_id,
                idempotency_key="second-key",
            )
        )

    assert drift.value.code == "idempotency_conflict"
    assert duplicate.value.code == "follow_up_materialization_already_prepared"


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("root_id", str(uuid.uuid4()), "materialization_root_mismatch"),
        ("intent_id", str(uuid.uuid4()), "materialization_intent_mismatch"),
        ("product_id", "ETH-USDC", "materialization_product_mismatch"),
        ("child_side", "BUY", "materialization_side_mismatch"),
        ("base_size", Decimal("0.5"), "materialization_size_mismatch"),
        (
            "portfolio_id",
            "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
            "materialization_portfolio_mismatch",
        ),
    ],
)
def test_prepare_revalidates_every_backend_derived_plan_identity(
    repository_harness: _RepositoryHarness,
    field: str,
    value: object,
    code: str,
):
    repository, root_id, source_id, intent_id = _attach_then_fill(
        repository_harness
    )
    values = {
        "source_id": source_id,
        "root_id": root_id,
        "intent_id": intent_id,
        "product_id": KNOWN_PRODUCT_ID,
        "child_side": "SELL",
        "base_size": Decimal("1"),
        "portfolio_id": PORTFOLIO_ID,
    }
    values[field] = value

    with pytest.raises(FollowUpIntentStoreConflict) as exc_info:
        repository.prepare_materialization(_materialization_command(**values))

    assert exc_info.value.code == code


def test_create_and_cancel_call_boundaries_are_append_only_and_one_use(
    repository_harness: _RepositoryHarness,
):
    repository, root_id, source_id, intent_id = _attach_then_fill(
        repository_harness
    )
    prepared = repository.prepare_materialization(
        _materialization_command(
            source_id=source_id,
            root_id=root_id,
            intent_id=intent_id,
        )
    )
    materialization_id = prepared.attempt.materialization_id

    create_started = repository.mark_create_invocation_started(materialization_id)
    create_replay = repository.mark_create_invocation_started(materialization_id)
    created = repository.record_create_result(
        materialization_id,
        outcome=FollowUpMaterializationState.CREATE_ACCEPTED_NONTERMINAL.value,
        diagnostic_code="create_accepted_nonterminal",
        exchange_order_id_sha256="a" * 64,
    )
    cancel_started = repository.mark_cancel_invocation_started(
        materialization_id,
        **_operation_authority("cancel-one-use-key"),
    )
    cancel_replay = repository.mark_cancel_invocation_started(
        materialization_id,
        **_operation_authority("cancel-one-use-key"),
    )
    cancelled_unknown = repository.record_cancel_result(
        materialization_id,
        outcome=FollowUpMaterializationState.CANCEL_UNKNOWN_CONSUMED.value,
        diagnostic_code="cancel_unknown_consumed",
    )

    assert create_started.replayed is False
    assert create_replay.replayed is True
    assert created.attempt.current_state == "CREATE_ACCEPTED_NONTERMINAL"
    assert cancel_started.replayed is False
    assert cancel_replay.replayed is True
    assert cancelled_unknown.attempt.current_state == "CANCEL_UNKNOWN_CONSUMED"
    assert cancelled_unknown.attempt.operation_idempotency_key_sha256 == (
        hashlib.sha256(b"cancel-one-use-key").hexdigest()
    )
    assert cancelled_unknown.attempt.current_operation_audit_id == (
        cancel_started.event.operation_audit_id
    )
    assert cancelled_unknown.attempt.current_operation_actor_id == (
        "operator-closeout-001"
    )
    assert cancelled_unknown.attempt.current_operation_roles == ("trader",)
    assert cancelled_unknown.attempt.current_operation_operator_intent == (
        "authorize_safe_closeout"
    )
    events = repository.list_materialization_events(materialization_id)
    create_events = events[:3]
    cancel_events = events[3:]
    assert {event.operation_audit_id for event in create_events} == {
        prepared.attempt.audit_id
    }
    assert {event.operation_audit_id for event in cancel_events} == {
        cancel_started.event.operation_audit_id
    }
    assert cancel_started.event.operation_audit_id != prepared.attempt.audit_id
    assert all(event.actor_id == "operator-test-001" for event in create_events)
    assert all(event.actor_id == "operator-closeout-001" for event in cancel_events)
    assert all(event.roles == ("trader",) for event in cancel_events)
    assert all(event.environment == "local" for event in cancel_events)
    assert all(
        event.operator_intent == "authorize_safe_closeout"
        for event in cancel_events
    )
    assert all(
        event.correlation_id == "corr-safe-closeout-001"
        for event in cancel_events
    )
    assert repository.list_materialization_events_by_operation_audit_id(
        cancel_started.event.operation_audit_id
    ) == tuple(cancel_events)
    with pytest.raises(FollowUpIntentStoreConflict) as second_cancel:
        repository.mark_cancel_invocation_started(
            materialization_id,
            **_operation_authority("cancel-one-use-key"),
        )
    assert second_cancel.value.code == "cancel_boundary_consumed"
    assert repository_harness.scalar(
        f'SELECT COUNT(*) FROM "{repository_harness.schema}".'
        "operator_follow_up_materialization_event"
    ) == 5


def test_cancel_boundary_rejects_changed_operation_idempotency_key(
    repository_harness: _RepositoryHarness,
):
    repository, root_id, source_id, intent_id = _attach_then_fill(
        repository_harness
    )
    attempt = repository.prepare_materialization(
        _materialization_command(
            source_id=source_id,
            root_id=root_id,
            intent_id=intent_id,
        )
    ).attempt
    repository.mark_create_invocation_started(attempt.materialization_id)
    repository.record_create_result(
        attempt.materialization_id,
        outcome=FollowUpMaterializationState.CREATE_ACCEPTED_NONTERMINAL.value,
        diagnostic_code="create_accepted_nonterminal",
    )
    repository.mark_cancel_invocation_started(
        attempt.materialization_id,
        **_operation_authority("cancel-key-one"),
    )

    with pytest.raises(FollowUpIntentStoreConflict) as exc_info:
        repository.mark_cancel_invocation_started(
            attempt.materialization_id,
            **_operation_authority("cancel-key-two"),
        )

    assert exc_info.value.code == "idempotency_conflict"

    with pytest.raises(FollowUpIntentStoreConflict) as caller_echo:
        repository.mark_cancel_invocation_started(
            attempt.materialization_id,
            **_operation_authority(
                "cancel-key-one",
                actor_id="different-operator",
                correlation_id="corr-caller-echo",
            ),
        )
    assert caller_echo.value.code == "idempotency_conflict"
    original = repository.list_materialization_events(
        attempt.materialization_id
    )[-1]
    assert original.actor_id == "operator-closeout-001"
    assert original.correlation_id == "corr-safe-closeout-001"


def test_authoritative_terminal_reconciliation_does_not_consume_cancel(
    repository_harness: _RepositoryHarness,
):
    repository, root_id, source_id, intent_id = _attach_then_fill(
        repository_harness
    )
    attempt = repository.prepare_materialization(
        _materialization_command(
            source_id=source_id,
            root_id=root_id,
            intent_id=intent_id,
        )
    ).attempt
    repository.mark_create_invocation_started(attempt.materialization_id)
    repository.record_create_result(
        attempt.materialization_id,
        outcome=FollowUpMaterializationState.CREATE_ACCEPTED_NONTERMINAL.value,
        diagnostic_code="create_accepted_nonterminal",
    )

    terminal = repository.record_child_terminal_without_cancel(
        attempt.materialization_id,
        diagnostic_code="child_terminal_reconciled",
        **_operation_authority("terminal-read-key"),
    )

    assert terminal.attempt.current_state == "CANCEL_NOT_REQUIRED_TERMINAL"
    assert terminal.attempt.operation_idempotency_key_sha256 == hashlib.sha256(
        b"terminal-read-key"
    ).hexdigest()
    terminal_event = terminal.event
    assert terminal_event.operation_audit_id != attempt.audit_id
    assert terminal_event.actor_id == "operator-closeout-001"
    assert terminal_event.operator_intent == "authorize_safe_closeout"
    assert repository_harness.scalar(
        f'SELECT COUNT(*) FROM "{repository_harness.schema}".'
        "operator_follow_up_materialization_event "
        "WHERE materialization_id = %s AND state = 'CANCEL_INVOCATION_STARTED'",
        (attempt.materialization_id,),
    ) == 0


@pytest.mark.parametrize(
    "outcome",
    [
        FollowUpMaterializationState.CREATE_EXPLICITLY_REJECTED.value,
        FollowUpMaterializationState.CREATE_ACCEPTED_TERMINAL.value,
    ],
)
def test_create_terminal_outcomes_cannot_mint_a_cancel_boundary(
    repository_harness: _RepositoryHarness,
    outcome: str,
):
    repository, root_id, source_id, intent_id = _attach_then_fill(
        repository_harness
    )
    attempt = repository.prepare_materialization(
        _materialization_command(
            source_id=source_id,
            root_id=root_id,
            intent_id=intent_id,
        )
    ).attempt
    repository.mark_create_invocation_started(attempt.materialization_id)
    repository.record_create_result(
        attempt.materialization_id,
        outcome=outcome,
        diagnostic_code=outcome.lower(),
    )

    with pytest.raises(FollowUpIntentStoreConflict) as exc_info:
        repository.mark_cancel_invocation_started(
            attempt.materialization_id,
            **_operation_authority("unused-cancel-key"),
        )

    assert exc_info.value.code == "cancel_not_eligible"


def test_unknown_create_can_use_separate_cancel_boundary_after_exact_reconciliation(
    repository_harness: _RepositoryHarness,
):
    repository, root_id, source_id, intent_id = _attach_then_fill(
        repository_harness
    )
    attempt = repository.prepare_materialization(
        _materialization_command(
            source_id=source_id,
            root_id=root_id,
            intent_id=intent_id,
        )
    ).attempt
    repository.mark_create_invocation_started(attempt.materialization_id)
    repository.record_create_result(
        attempt.materialization_id,
        outcome=FollowUpMaterializationState.CREATE_UNKNOWN_CONSUMED.value,
        diagnostic_code="create_unknown_consumed",
    )

    cancel = repository.mark_cancel_invocation_started(
        attempt.materialization_id,
        **_operation_authority("safe-closeout-after-exact-reconciliation"),
    )

    assert cancel.replayed is False
    assert cancel.attempt.current_state == "CANCEL_INVOCATION_STARTED"


def test_unknown_create_exact_terminal_reconciliation_consumes_no_cancel(
    repository_harness: _RepositoryHarness,
):
    repository, root_id, source_id, intent_id = _attach_then_fill(
        repository_harness
    )
    attempt = repository.prepare_materialization(
        _materialization_command(
            source_id=source_id,
            root_id=root_id,
            intent_id=intent_id,
        )
    ).attempt
    repository.mark_create_invocation_started(attempt.materialization_id)
    repository.record_create_result(
        attempt.materialization_id,
        outcome=FollowUpMaterializationState.CREATE_UNKNOWN_CONSUMED.value,
        diagnostic_code="create_unknown_consumed",
    )

    terminal = repository.record_child_terminal_without_cancel(
        attempt.materialization_id,
        diagnostic_code="child_terminal_reconciled",
        **_operation_authority("terminal-after-unknown-key"),
    )

    assert terminal.attempt.current_state == "CANCEL_NOT_REQUIRED_TERMINAL"
    assert repository_harness.scalar(
        f'SELECT COUNT(*) FROM "{repository_harness.schema}".'
        "operator_follow_up_materialization_event "
        "WHERE materialization_id = %s AND state = 'CANCEL_INVOCATION_STARTED'",
        (attempt.materialization_id,),
    ) == 0


def test_terminal_without_cancel_replay_binds_exact_operation_key(
    repository_harness: _RepositoryHarness,
):
    repository, root_id, source_id, intent_id = _attach_then_fill(
        repository_harness
    )
    attempt = repository.prepare_materialization(
        _materialization_command(
            source_id=source_id,
            root_id=root_id,
            intent_id=intent_id,
        )
    ).attempt
    repository.mark_create_invocation_started(attempt.materialization_id)
    repository.record_create_result(
        attempt.materialization_id,
        outcome=FollowUpMaterializationState.CREATE_ACCEPTED_NONTERMINAL.value,
        diagnostic_code="create_accepted_nonterminal",
    )
    key_hash = hashlib.sha256(b"terminal-exact-key").hexdigest()

    first = repository.record_child_terminal_without_cancel(
        attempt.materialization_id,
        diagnostic_code="child_terminal_reconciled",
        **_operation_authority("terminal-exact-key"),
    )
    replay = repository.record_child_terminal_without_cancel(
        attempt.materialization_id,
        diagnostic_code="child_terminal_reconciled",
        **_operation_authority("terminal-exact-key"),
    )

    assert first.replayed is False
    assert replay.replayed is True
    assert replay.attempt.operation_idempotency_key_sha256 == key_hash
    assert replay.event == first.event
    assert replay.event.operation_audit_id == first.event.operation_audit_id
    with pytest.raises(FollowUpIntentStoreConflict) as changed_key:
        repository.record_child_terminal_without_cancel(
            attempt.materialization_id,
            diagnostic_code="child_terminal_reconciled",
            **_operation_authority("different-terminal-key"),
        )
    assert changed_key.value.code == "idempotency_conflict"
    with pytest.raises(FollowUpIntentStoreConflict) as changed_caller:
        repository.record_child_terminal_without_cancel(
            attempt.materialization_id,
            diagnostic_code="child_terminal_reconciled",
            **_operation_authority(
                "terminal-exact-key",
                correlation_id="corr-not-the-original",
            ),
        )
    assert changed_caller.value.code == "idempotency_conflict"


def test_lineage_trigger_permits_only_the_exact_preclaimed_flat_child(
    repository_harness: _RepositoryHarness,
):
    repository, root_id, source_id, intent_id = _attach_then_fill(
        repository_harness
    )
    attempt = repository.prepare_materialization(
        _materialization_command(
            source_id=source_id,
            root_id=root_id,
            intent_id=intent_id,
        )
    ).attempt

    _insert_planned_child(
        repository_harness,
        child_id=attempt.child_client_order_id,
        root_id=root_id,
    )

    assert repository_harness.scalar(
        f'SELECT COUNT(*) FROM "{repository_harness.schema}".order_parent '
        "WHERE client_order_id = %s",
        (attempt.child_client_order_id,),
    ) == 1
    with pytest.raises(psycopg2.Error) as sibling:
        _insert_order(
            repository_harness,
            client_order_id=str(uuid.uuid4()),
            product_id=KNOWN_PRODUCT_ID,
            side="SELL",
            status="PENDING",
            parent_order_id=root_id,
            ownership_provenance="ADMIN_FILL_FOLLOW_UP",
        )
    with pytest.raises(psycopg2.Error) as nested:
        _insert_order(
            repository_harness,
            client_order_id=str(uuid.uuid4()),
            product_id=KNOWN_PRODUCT_ID,
            side="BUY",
            status="PENDING",
            parent_order_id=source_id,
            ownership_provenance="ADMIN_FILL_FOLLOW_UP",
        )

    assert sibling.value.pgcode == "P0001"
    assert nested.value.pgcode == "P0001"


def test_lineage_trigger_rejects_exact_id_with_plan_drift(
    repository_harness: _RepositoryHarness,
):
    repository, root_id, source_id, intent_id = _attach_then_fill(
        repository_harness
    )
    attempt = repository.prepare_materialization(
        _materialization_command(
            source_id=source_id,
            root_id=root_id,
            intent_id=intent_id,
        )
    ).attempt

    with pytest.raises(psycopg2.Error) as exc_info:
        _insert_planned_child(
            repository_harness,
            child_id=attempt.child_client_order_id,
            root_id=root_id,
            side="BUY",
        )

    assert exc_info.value.pgcode == "P0001"
    assert "operator_follow_up_intent_lineage_locked" in str(exc_info.value)


def test_materialization_claim_and_journal_reject_update_or_delete(
    repository_harness: _RepositoryHarness,
):
    repository, root_id, source_id, intent_id = _attach_then_fill(
        repository_harness
    )
    attempt = repository.prepare_materialization(
        _materialization_command(
            source_id=source_id,
            root_id=root_id,
            intent_id=intent_id,
        )
    ).attempt

    with pytest.raises(psycopg2.Error) as update_attempt:
        repository_harness.execute(
            f'UPDATE "{repository_harness.schema}".'
            "operator_follow_up_materialization_attempt "
            "SET product_id = 'ETH-USDC' WHERE materialization_id = %s",
            (attempt.materialization_id,),
        )
    with pytest.raises(psycopg2.Error) as delete_event:
        repository_harness.execute(
            f'DELETE FROM "{repository_harness.schema}".'
            "operator_follow_up_materialization_event "
            "WHERE materialization_id = %s",
            (attempt.materialization_id,),
        )

    assert update_attempt.value.pgcode == "P0001"
    assert delete_event.value.pgcode == "P0001"


def test_materialization_audit_context_and_sanitized_events_survive_readback(
    repository_harness: _RepositoryHarness,
):
    repository, root_id, source_id, intent_id = _attach_then_fill(
        repository_harness
    )
    prepared = repository.prepare_materialization(
        _materialization_command(
            source_id=source_id,
            root_id=root_id,
            intent_id=intent_id,
        )
    )
    repository.mark_create_invocation_started(prepared.attempt.materialization_id)
    repository.record_create_result(
        prepared.attempt.materialization_id,
        outcome=FollowUpMaterializationState.CREATE_EXPLICITLY_REJECTED.value,
        diagnostic_code="create_explicitly_rejected",
    )

    attempt = repository.read_materialization(source_id).attempt
    events = repository.list_materialization_events(
        prepared.attempt.materialization_id
    )

    assert attempt is not None
    assert uuid.UUID(attempt.audit_id)
    assert attempt.actor_id == "operator-test-001"
    assert attempt.roles == ("trader",)
    assert attempt.environment == "local"
    assert attempt.correlation_id.startswith("corr-")
    assert attempt.operator_intent == "authorize_and_materialize_follow_up_intent"
    assert attempt.current_state == "CREATE_EXPLICITLY_REJECTED"
    assert attempt.exchange_order_id_sha256 is None
    assert [event.state for event in events] == [
        "KNOWN_NOT_INVOKED",
        "CREATE_INVOCATION_STARTED",
        "CREATE_EXPLICITLY_REJECTED",
    ]
    assert all(event.exchange_order_id_sha256 is None for event in events)
    prepare_hash = hashlib.sha256(
        prepared.attempt.idempotency_key.encode("utf-8")
    ).hexdigest()
    assert all(
        event.operation_audit_id == prepared.attempt.audit_id
        for event in events
    )
    assert all(event.actor_id == prepared.attempt.actor_id for event in events)
    assert all(event.roles == prepared.attempt.roles for event in events)
    assert all(
        event.environment == prepared.attempt.environment for event in events
    )
    assert all(
        event.operator_intent == prepared.attempt.operator_intent
        for event in events
    )
    assert all(
        event.correlation_id == prepared.attempt.correlation_id
        for event in events
    )
    assert all(
        event.operation_idempotency_key_sha256 == prepare_hash
        for event in events
    )
    assert repository_harness.scalar(
        f'SELECT COUNT(*) FROM "{repository_harness.schema}".'
        "operator_follow_up_materialization_event "
        "WHERE materialization_id = %s",
        (attempt.materialization_id,),
    ) == 3


def test_schema_upgrade_backfills_queryable_create_operation_bindings(
    repository_harness: _RepositoryHarness,
):
    repository, root_id, source_id, intent_id = _attach_then_fill(
        repository_harness
    )
    prepared = repository.prepare_materialization(
        _materialization_command(
            source_id=source_id,
            root_id=root_id,
            intent_id=intent_id,
        )
    )
    repository.mark_create_invocation_started(prepared.attempt.materialization_id)
    repository.record_create_result(
        prepared.attempt.materialization_id,
        outcome=FollowUpMaterializationState.CREATE_EXPLICITLY_REJECTED.value,
        diagnostic_code="create_explicitly_rejected",
    )
    table = (
        f'"{repository_harness.schema}".'
        "operator_follow_up_materialization_event"
    )
    repository_harness.execute(
        f"DROP TRIGGER operator_follow_up_materialization_event_append_only "
        f"ON {table}"
    )
    for column in (
        "operation_audit_id",
        "operation_actor_id",
        "operation_roles_json",
        "operation_environment",
        "operation_operator_intent",
        "operation_correlation_id",
    ):
        repository_harness.execute(
            f"ALTER TABLE {table} DROP COLUMN {column}"
        )

    upgraded = repository_harness.repository()
    events = upgraded.list_materialization_events(
        prepared.attempt.materialization_id
    )

    assert len(events) == 3
    assert all(
        event.operation_audit_id == prepared.attempt.audit_id
        for event in events
    )
    assert all(event.actor_id == "operator-test-001" for event in events)
    assert all(event.roles == ("trader",) for event in events)
    assert all(event.environment == "local" for event in events)
    assert all(
        event.operator_intent == "authorize_and_materialize_follow_up_intent"
        for event in events
    )
    assert all(
        event.correlation_id == prepared.attempt.correlation_id
        for event in events
    )


def test_atomic_local_child_create_acceptance_is_truthful_and_replay_safe(
    repository_harness: _RepositoryHarness,
    monkeypatch: pytest.MonkeyPatch,
):
    repository, root_id, source_id, intent_id = _attach_then_fill(
        repository_harness
    )
    prepared = repository.prepare_materialization(
        _materialization_command(
            source_id=source_id,
            root_id=root_id,
            intent_id=intent_id,
        )
    )
    _persist_quarantined_stealth_child(
        repository_harness,
        materialization_id=prepared.attempt.materialization_id,
        child_id=prepared.attempt.child_client_order_id,
        root_id=root_id,
    )
    repository.mark_create_invocation_started(prepared.attempt.materialization_id)
    result = repository.record_create_result(
        prepared.attempt.materialization_id,
        outcome=FollowUpMaterializationState.CREATE_ACCEPTED_NONTERMINAL.value,
        diagnostic_code="create_accepted_nonterminal",
        exchange_order_id_sha256=hashlib.sha256(b"exchange-child-one").hexdigest(),
    )

    first = repository.transition_materialized_child_local_state(
        materialization_id=prepared.attempt.materialization_id,
        transition_kind=(
            FollowUpMaterializedChildTransitionKind.CREATE_ACCEPTED_ACTIVE.value
        ),
        authoritative_order_status="OPEN",
        exchange_order_id="exchange-child-one",
        operation_audit_id=result.event.operation_audit_id,
        operation_idempotency_key_sha256=(
            result.event.operation_idempotency_key_sha256
        ),
    )
    replay = repository.transition_materialized_child_local_state(
        materialization_id=prepared.attempt.materialization_id,
        transition_kind=(
            FollowUpMaterializedChildTransitionKind.CREATE_ACCEPTED_ACTIVE.value
        ),
        authoritative_order_status="OPEN",
        exchange_order_id="exchange-child-one",
        operation_audit_id=result.event.operation_audit_id,
        operation_idempotency_key_sha256=(
            result.event.operation_idempotency_key_sha256
        ),
    )

    assert first.replayed is False
    assert replay.replayed is True
    assert replay.record == first.record
    assert first.record.exchange_order_id_sha256 == hashlib.sha256(
        b"exchange-child-one"
    ).hexdigest()
    child = _row_mapping(
        repository_harness,
        f'SELECT * FROM "{repository_harness.schema}".order_parent '
        "WHERE client_order_id = %s",
        (prepared.attempt.child_client_order_id,),
    )
    stealth = _row_mapping(
        repository_harness,
        f'SELECT * FROM "{repository_harness.schema}".stealth_orders '
        "WHERE stealth_order_id = %s",
        (prepared.attempt.child_client_order_id,),
    )
    assert child["status"] == "OPEN"
    assert child["exchange_order_id"] == "exchange-child-one"
    assert stealth["status"] == "REVEALED"
    assert Decimal(str(stealth["remaining_size"])) == 0
    assert stealth["revealed_orders"][0]["placed_order_id"] == (
        prepared.attempt.child_client_order_id
    )
    assert stealth["revealed_orders"][0]["exchange_order_id"] == (
        "exchange-child-one"
    )
    assert stealth["anchor_repricing_state_json"][
        "active_placement_client_order_id"
    ] == prepared.attempt.child_client_order_id

    with pytest.raises(FollowUpIntentStoreConflict) as drift:
        repository.transition_materialized_child_local_state(
            materialization_id=prepared.attempt.materialization_id,
            transition_kind=(
                FollowUpMaterializedChildTransitionKind.CREATE_ACCEPTED_ACTIVE.value
            ),
            authoritative_order_status="OPEN",
            exchange_order_id="different-exchange-child",
            operation_audit_id=result.event.operation_audit_id,
            operation_idempotency_key_sha256=(
                result.event.operation_idempotency_key_sha256
            ),
        )
    assert drift.value.code == "materialized_child_local_state_conflict"

    repository._schema_ready = False

    def fail_if_schema_mutates() -> None:
        raise AssertionError("projection read attempted DDL")

    monkeypatch.setattr(repository, "ensure_schema", fail_if_schema_mutates)
    assert repository.read_latest_materialized_child_local_state(
        prepared.attempt.materialization_id
    ) == first.record
    repository_harness.execute(
        f'UPDATE "{repository_harness.schema}".order_parent '
        "SET status = 'PENDING' WHERE client_order_id = %s",
        (prepared.attempt.child_client_order_id,),
    )
    with pytest.raises(FollowUpIntentStoreConflict) as read_drift:
        repository.read_latest_materialized_child_local_state(
            prepared.attempt.materialization_id
        )
    assert read_drift.value.code == "materialized_child_local_state_mismatch"


def test_unknown_child_stays_quarantined_then_exact_terminal_reconciliation(
    repository_harness: _RepositoryHarness,
):
    repository, root_id, source_id, intent_id = _attach_then_fill(
        repository_harness
    )
    prepared = repository.prepare_materialization(
        _materialization_command(
            source_id=source_id,
            root_id=root_id,
            intent_id=intent_id,
        )
    )
    _persist_quarantined_stealth_child(
        repository_harness,
        materialization_id=prepared.attempt.materialization_id,
        child_id=prepared.attempt.child_client_order_id,
        root_id=root_id,
    )
    repository.mark_create_invocation_started(prepared.attempt.materialization_id)
    unknown = repository.record_create_result(
        prepared.attempt.materialization_id,
        outcome=FollowUpMaterializationState.CREATE_UNKNOWN_CONSUMED.value,
        diagnostic_code="create_unknown_consumed",
    )
    repository.transition_materialized_child_local_state(
        materialization_id=prepared.attempt.materialization_id,
        transition_kind=(
            FollowUpMaterializedChildTransitionKind.CREATE_UNKNOWN_QUARANTINED.value
        ),
        authoritative_order_status="SUBMISSION_UNKNOWN",
        exchange_order_id=None,
        operation_audit_id=unknown.event.operation_audit_id,
        operation_idempotency_key_sha256=(
            unknown.event.operation_idempotency_key_sha256
        ),
    )
    terminal = repository.record_child_terminal_without_cancel(
        prepared.attempt.materialization_id,
        diagnostic_code="child_terminal_reconciled",
        exchange_order_id_sha256=hashlib.sha256(
            b"exchange-child-terminal"
        ).hexdigest(),
        **_operation_authority("terminal-reconciliation-key"),
    )

    reconciled = repository.transition_materialized_child_local_state(
        materialization_id=prepared.attempt.materialization_id,
        transition_kind=(
            FollowUpMaterializedChildTransitionKind.TERMINAL_WITHOUT_CANCEL.value
        ),
        authoritative_order_status="FILLED",
        exchange_order_id="exchange-child-terminal",
        operation_audit_id=terminal.event.operation_audit_id,
        operation_idempotency_key_sha256=(
            terminal.event.operation_idempotency_key_sha256
        ),
    )

    assert reconciled.record.authoritative_order_status == "FILLED"
    child = _row_mapping(
        repository_harness,
        f'SELECT status, exchange_order_id FROM "{repository_harness.schema}".'
        "order_parent WHERE client_order_id = %s",
        (prepared.attempt.child_client_order_id,),
    )
    stealth = _row_mapping(
        repository_harness,
        f'SELECT status, executed_size, anchor_repricing_state_json '
        f'FROM "{repository_harness.schema}".stealth_orders '
        "WHERE stealth_order_id = %s",
        (prepared.attempt.child_client_order_id,),
    )
    assert child == {
        "status": "FILLED",
        "exchange_order_id": "exchange-child-terminal",
    }
    assert stealth["status"] == "EXECUTED"
    assert Decimal(str(stealth["executed_size"])) == Decimal("1")
    assert "active_placement_client_order_id" not in (
        stealth["anchor_repricing_state_json"]
    )


def test_cancel_terminal_local_transition_reuses_exact_exchange_identity(
    repository_harness: _RepositoryHarness,
):
    repository, root_id, source_id, intent_id = _attach_then_fill(
        repository_harness
    )
    prepared = repository.prepare_materialization(
        _materialization_command(
            source_id=source_id,
            root_id=root_id,
            intent_id=intent_id,
        )
    )
    _persist_quarantined_stealth_child(
        repository_harness,
        materialization_id=prepared.attempt.materialization_id,
        child_id=prepared.attempt.child_client_order_id,
        root_id=root_id,
    )
    repository.mark_create_invocation_started(prepared.attempt.materialization_id)
    created = repository.record_create_result(
        prepared.attempt.materialization_id,
        outcome=FollowUpMaterializationState.CREATE_ACCEPTED_NONTERMINAL.value,
        diagnostic_code="create_accepted_nonterminal",
        exchange_order_id_sha256=hashlib.sha256(b"exchange-to-cancel").hexdigest(),
    )
    repository.transition_materialized_child_local_state(
        materialization_id=prepared.attempt.materialization_id,
        transition_kind=(
            FollowUpMaterializedChildTransitionKind.CREATE_ACCEPTED_ACTIVE.value
        ),
        authoritative_order_status="OPEN",
        exchange_order_id="exchange-to-cancel",
        operation_audit_id=created.event.operation_audit_id,
        operation_idempotency_key_sha256=(
            created.event.operation_idempotency_key_sha256
        ),
    )
    repository.mark_cancel_invocation_started(
        prepared.attempt.materialization_id,
        **_operation_authority("cancel-terminal-key"),
    )
    cancelled = repository.record_cancel_result(
        prepared.attempt.materialization_id,
        outcome=FollowUpMaterializationState.CANCEL_ACCEPTED_TERMINAL.value,
        diagnostic_code="cancel_accepted_terminal",
        exchange_order_id_sha256=hashlib.sha256(b"exchange-to-cancel").hexdigest(),
    )

    local = repository.transition_materialized_child_local_state(
        materialization_id=prepared.attempt.materialization_id,
        transition_kind=(
            FollowUpMaterializedChildTransitionKind.CANCEL_ACCEPTED_TERMINAL.value
        ),
        authoritative_order_status="CANCELLED",
        exchange_order_id="exchange-to-cancel",
        operation_audit_id=cancelled.event.operation_audit_id,
        operation_idempotency_key_sha256=(
            cancelled.event.operation_idempotency_key_sha256
        ),
    )

    assert local.record.authoritative_order_status == "CANCELLED"
    stealth = _row_mapping(
        repository_harness,
        f'SELECT status, anchor_repricing_state_json '
        f'FROM "{repository_harness.schema}".stealth_orders '
        "WHERE stealth_order_id = %s",
        (prepared.attempt.child_client_order_id,),
    )
    assert stealth["status"] == "CANCELLED"
    assert "active_placement_client_order_id" not in (
        stealth["anchor_repricing_state_json"]
    )


def test_local_child_transition_fails_atomically_on_stealth_identity_drift(
    repository_harness: _RepositoryHarness,
):
    repository, root_id, source_id, intent_id = _attach_then_fill(
        repository_harness
    )
    prepared = repository.prepare_materialization(
        _materialization_command(
            source_id=source_id,
            root_id=root_id,
            intent_id=intent_id,
        )
    )
    _persist_quarantined_stealth_child(
        repository_harness,
        materialization_id=prepared.attempt.materialization_id,
        child_id=prepared.attempt.child_client_order_id,
        root_id=root_id,
    )
    repository_harness.execute(
        f'UPDATE "{repository_harness.schema}".stealth_orders '
        "SET product_id = 'ETH-USDC' WHERE stealth_order_id = %s",
        (prepared.attempt.child_client_order_id,),
    )
    repository.mark_create_invocation_started(prepared.attempt.materialization_id)
    result = repository.record_create_result(
        prepared.attempt.materialization_id,
        outcome=FollowUpMaterializationState.CREATE_ACCEPTED_NONTERMINAL.value,
        diagnostic_code="create_accepted_nonterminal",
        exchange_order_id_sha256=hashlib.sha256(b"exchange-drift").hexdigest(),
    )

    with pytest.raises(FollowUpIntentStoreConflict) as exc_info:
        repository.transition_materialized_child_local_state(
            materialization_id=prepared.attempt.materialization_id,
            transition_kind=(
                FollowUpMaterializedChildTransitionKind.CREATE_ACCEPTED_ACTIVE.value
            ),
            authoritative_order_status="OPEN",
            exchange_order_id="exchange-drift",
            operation_audit_id=result.event.operation_audit_id,
            operation_idempotency_key_sha256=(
                result.event.operation_idempotency_key_sha256
            ),
        )

    assert exc_info.value.code == "materialized_child_identity_mismatch"
    child = _row_mapping(
        repository_harness,
        f'SELECT status, exchange_order_id FROM "{repository_harness.schema}".'
        "order_parent WHERE client_order_id = %s",
        (prepared.attempt.child_client_order_id,),
    )
    assert child == {"status": "PENDING", "exchange_order_id": None}
    assert repository_harness.scalar(
        f'SELECT COUNT(*) FROM "{repository_harness.schema}".'
        "operator_follow_up_materialized_child_state_event"
    ) == 0


@pytest.mark.parametrize(
    (
        "outcome",
        "transition_kind",
        "order_status",
        "exchange_order_id",
        "expected_stealth_status",
    ),
    (
        (
            FollowUpMaterializationState.CREATE_EXPLICITLY_REJECTED.value,
            FollowUpMaterializedChildTransitionKind.CREATE_EXPLICITLY_REJECTED.value,
            "FAILED",
            None,
            "CANCELLED",
        ),
        (
            FollowUpMaterializationState.CREATE_ACCEPTED_TERMINAL.value,
            FollowUpMaterializedChildTransitionKind.CREATE_ACCEPTED_TERMINAL.value,
            "FILLED",
            "exchange-create-terminal",
            "EXECUTED",
        ),
    ),
)
def test_initial_terminal_local_projections_are_sanitized_and_exact(
    repository_harness: _RepositoryHarness,
    outcome: str,
    transition_kind: str,
    order_status: str,
    exchange_order_id: str | None,
    expected_stealth_status: str,
):
    repository, root_id, source_id, intent_id = _attach_then_fill(
        repository_harness
    )
    prepared = repository.prepare_materialization(
        _materialization_command(
            source_id=source_id,
            root_id=root_id,
            intent_id=intent_id,
        )
    )
    _persist_quarantined_stealth_child(
        repository_harness,
        materialization_id=prepared.attempt.materialization_id,
        child_id=prepared.attempt.child_client_order_id,
        root_id=root_id,
    )
    repository.mark_create_invocation_started(prepared.attempt.materialization_id)
    exchange_hash = (
        hashlib.sha256(exchange_order_id.encode("utf-8")).hexdigest()
        if exchange_order_id is not None
        else None
    )
    durable = repository.record_create_result(
        prepared.attempt.materialization_id,
        outcome=outcome,
        diagnostic_code=outcome.lower(),
        exchange_order_id_sha256=exchange_hash,
    )

    projected = repository.transition_materialized_child_local_state(
        materialization_id=prepared.attempt.materialization_id,
        transition_kind=transition_kind,
        authoritative_order_status=order_status,
        exchange_order_id=exchange_order_id,
        operation_audit_id=durable.event.operation_audit_id,
        operation_idempotency_key_sha256=(
            durable.event.operation_idempotency_key_sha256
        ),
    )

    assert projected.record.exchange_order_id_sha256 == exchange_hash
    if exchange_order_id is not None:
        assert exchange_order_id not in repr(projected.record)
    assert repository.read_latest_materialized_child_local_state(
        prepared.attempt.materialization_id
    ) == projected.record
    stealth = _row_mapping(
        repository_harness,
        f'SELECT status, remaining_size FROM "{repository_harness.schema}".'
        "stealth_orders WHERE stealth_order_id = %s",
        (prepared.attempt.child_client_order_id,),
    )
    assert stealth["status"] == expected_stealth_status
    assert Decimal(str(stealth["remaining_size"])) == 0


def test_unknown_reconciliation_and_cancel_unknown_reconcile_exactly_once(
    repository_harness: _RepositoryHarness,
):
    repository, root_id, source_id, intent_id = _attach_then_fill(
        repository_harness
    )
    prepared = repository.prepare_materialization(
        _materialization_command(
            source_id=source_id,
            root_id=root_id,
            intent_id=intent_id,
        )
    )
    _persist_quarantined_stealth_child(
        repository_harness,
        materialization_id=prepared.attempt.materialization_id,
        child_id=prepared.attempt.child_client_order_id,
        root_id=root_id,
    )
    repository.mark_create_invocation_started(prepared.attempt.materialization_id)
    create_unknown = repository.record_create_result(
        prepared.attempt.materialization_id,
        outcome=FollowUpMaterializationState.CREATE_UNKNOWN_CONSUMED.value,
        diagnostic_code="create_unknown_consumed",
    )
    repository.transition_materialized_child_local_state(
        materialization_id=prepared.attempt.materialization_id,
        transition_kind=(
            FollowUpMaterializedChildTransitionKind.CREATE_UNKNOWN_QUARANTINED.value
        ),
        authoritative_order_status="SUBMISSION_UNKNOWN",
        exchange_order_id=None,
        operation_audit_id=create_unknown.event.operation_audit_id,
        operation_idempotency_key_sha256=(
            create_unknown.event.operation_idempotency_key_sha256
        ),
    )
    reconciled_active = repository.transition_materialized_child_local_state(
        materialization_id=prepared.attempt.materialization_id,
        transition_kind=(
            FollowUpMaterializedChildTransitionKind.RECONCILED_ACTIVE.value
        ),
        authoritative_order_status="OPEN",
        exchange_order_id="exchange-reconciled-active",
        operation_audit_id=create_unknown.event.operation_audit_id,
        operation_idempotency_key_sha256=(
            create_unknown.event.operation_idempotency_key_sha256
        ),
    )
    repository.mark_cancel_invocation_started(
        prepared.attempt.materialization_id,
        **_operation_authority("cancel-unknown-key"),
    )
    exchange_hash = hashlib.sha256(
        b"exchange-reconciled-active"
    ).hexdigest()
    cancel_unknown = repository.record_cancel_result(
        prepared.attempt.materialization_id,
        outcome=FollowUpMaterializationState.CANCEL_UNKNOWN_CONSUMED.value,
        diagnostic_code="cancel_unknown_consumed",
        exchange_order_id_sha256=exchange_hash,
    )
    repository.transition_materialized_child_local_state(
        materialization_id=prepared.attempt.materialization_id,
        transition_kind=(
            FollowUpMaterializedChildTransitionKind.CANCEL_UNKNOWN_QUARANTINED.value
        ),
        authoritative_order_status="CANCEL_QUEUED",
        exchange_order_id="exchange-reconciled-active",
        operation_audit_id=cancel_unknown.event.operation_audit_id,
        operation_idempotency_key_sha256=(
            cancel_unknown.event.operation_idempotency_key_sha256
        ),
    )
    reconciled_terminal = repository.transition_materialized_child_local_state(
        materialization_id=prepared.attempt.materialization_id,
        transition_kind=(
            FollowUpMaterializedChildTransitionKind.RECONCILED_TERMINAL.value
        ),
        authoritative_order_status="CANCELLED",
        exchange_order_id="exchange-reconciled-active",
        operation_audit_id=cancel_unknown.event.operation_audit_id,
        operation_idempotency_key_sha256=(
            cancel_unknown.event.operation_idempotency_key_sha256
        ),
    )

    assert reconciled_active.record.exchange_order_id_sha256 == exchange_hash
    assert repository.read_latest_materialized_child_local_state(
        prepared.attempt.materialization_id
    ) == reconciled_terminal.record
    child = _row_mapping(
        repository_harness,
        f'SELECT status, exchange_order_id FROM "{repository_harness.schema}".'
        "order_parent WHERE client_order_id = %s",
        (prepared.attempt.child_client_order_id,),
    )
    assert child == {
        "status": "CANCELLED",
        "exchange_order_id": "exchange-reconciled-active",
    }


def test_cancel_rejection_is_a_new_operation_and_old_projection_is_stale(
    repository_harness: _RepositoryHarness,
):
    repository, root_id, source_id, intent_id = _attach_then_fill(
        repository_harness
    )
    prepared = repository.prepare_materialization(
        _materialization_command(
            source_id=source_id,
            root_id=root_id,
            intent_id=intent_id,
        )
    )
    _persist_quarantined_stealth_child(
        repository_harness,
        materialization_id=prepared.attempt.materialization_id,
        child_id=prepared.attempt.child_client_order_id,
        root_id=root_id,
    )
    repository.mark_create_invocation_started(prepared.attempt.materialization_id)
    exchange_hash = hashlib.sha256(b"exchange-cancel-rejected").hexdigest()
    created = repository.record_create_result(
        prepared.attempt.materialization_id,
        outcome=FollowUpMaterializationState.CREATE_ACCEPTED_NONTERMINAL.value,
        diagnostic_code="create_accepted_nonterminal",
        exchange_order_id_sha256=exchange_hash,
    )
    repository.transition_materialized_child_local_state(
        materialization_id=prepared.attempt.materialization_id,
        transition_kind=(
            FollowUpMaterializedChildTransitionKind.CREATE_ACCEPTED_ACTIVE.value
        ),
        authoritative_order_status="OPEN",
        exchange_order_id="exchange-cancel-rejected",
        operation_audit_id=created.event.operation_audit_id,
        operation_idempotency_key_sha256=(
            created.event.operation_idempotency_key_sha256
        ),
    )
    repository.mark_cancel_invocation_started(
        prepared.attempt.materialization_id,
        **_operation_authority("cancel-rejected-key"),
    )
    rejected = repository.record_cancel_result(
        prepared.attempt.materialization_id,
        outcome=FollowUpMaterializationState.CANCEL_EXPLICITLY_REJECTED.value,
        diagnostic_code="cancel_explicitly_rejected",
    )
    local_rejected = repository.transition_materialized_child_local_state(
        materialization_id=prepared.attempt.materialization_id,
        transition_kind=(
            FollowUpMaterializedChildTransitionKind.CANCEL_EXPLICITLY_REJECTED_ACTIVE.value
        ),
        authoritative_order_status="OPEN",
        exchange_order_id="exchange-cancel-rejected",
        operation_audit_id=rejected.event.operation_audit_id,
        operation_idempotency_key_sha256=(
            rejected.event.operation_idempotency_key_sha256
        ),
    )

    with pytest.raises(FollowUpIntentStoreConflict) as stale:
        repository.transition_materialized_child_local_state(
            materialization_id=prepared.attempt.materialization_id,
            transition_kind=(
                FollowUpMaterializedChildTransitionKind.CREATE_ACCEPTED_ACTIVE.value
            ),
            authoritative_order_status="OPEN",
            exchange_order_id="exchange-cancel-rejected",
            operation_audit_id=created.event.operation_audit_id,
            operation_idempotency_key_sha256=(
                created.event.operation_idempotency_key_sha256
            ),
        )
    assert stale.value.code == "materialized_child_local_state_conflict"
    assert repository.read_latest_materialized_child_local_state(
        prepared.attempt.materialization_id
    ) == local_rejected.record


def test_direct_root_materialized_child_keeps_flat_lineage(
    repository_harness: _RepositoryHarness,
):
    root_id = str(uuid.uuid4())
    _insert_order(
        repository_harness,
        client_order_id=root_id,
        product_id=KNOWN_PRODUCT_ID,
        side="BUY",
        status="OPEN",
        parent_order_id=None,
        ownership_provenance="ADMIN_MANUAL_ROOT",
    )
    repository = repository_harness.repository()
    attached = repository.attach(_command(root_id))
    repository_harness.execute(
        f'UPDATE "{repository_harness.schema}".order_parent '
        "SET status = 'FILLED' WHERE client_order_id = %s",
        (root_id,),
    )
    repository_harness.execute(
        f"""
        INSERT INTO "{repository_harness.schema}".fill_ledger (
            derived_trade_key, instrument, side, quantity, price,
            client_order_id
        ) VALUES (%s, %s, 'BUY', 1, 100, %s)
        """,
        (str(uuid.uuid4()), KNOWN_PRODUCT_ID, root_id),
    )
    prepared = repository.prepare_materialization(
        _materialization_command(
            source_id=root_id,
            root_id=root_id,
            intent_id=attached.record.follow_up_intent_id,
        )
    )
    _persist_quarantined_stealth_child(
        repository_harness,
        materialization_id=prepared.attempt.materialization_id,
        child_id=prepared.attempt.child_client_order_id,
        root_id=root_id,
    )
    repository.mark_create_invocation_started(prepared.attempt.materialization_id)
    rejected = repository.record_create_result(
        prepared.attempt.materialization_id,
        outcome=FollowUpMaterializationState.CREATE_EXPLICITLY_REJECTED.value,
        diagnostic_code="create_explicitly_rejected",
    )

    projected = repository.transition_materialized_child_local_state(
        materialization_id=prepared.attempt.materialization_id,
        transition_kind=(
            FollowUpMaterializedChildTransitionKind.CREATE_EXPLICITLY_REJECTED.value
        ),
        authoritative_order_status="FAILED",
        exchange_order_id=None,
        operation_audit_id=rejected.event.operation_audit_id,
        operation_idempotency_key_sha256=(
            rejected.event.operation_idempotency_key_sha256
        ),
    )

    assert projected.replayed is False
    assert repository_harness.scalar(
        f'SELECT COUNT(*) FROM "{repository_harness.schema}".order_parent '
        "WHERE parent_order_id = %s",
        (root_id,),
    ) == 1
