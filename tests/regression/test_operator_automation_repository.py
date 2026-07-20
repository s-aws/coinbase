"""Real-PostgreSQL contract for the operator Automation control plane."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import os
import re
import threading
import uuid

import psycopg2
from psycopg2 import sql
import pytest

from core.enums import (
    OperatorAutomationControlPosture,
    OperatorAutomationDefinitionState,
    OperatorAutomationDomain,
    OperatorAutomationJobKind,
    OperatorAutomationRunState,
    OperatorAutomationScheduleKind,
)
from database.database import PostgresDB
from database.operator_automation import (
    AutomationDefinitionCreateCommand,
    AutomationMutationCommand,
    AutomationSpotSingleChildPlanTerms,
    AUTOMATION_SPOT_ELIGIBILITY_CATEGORIES,
    AutomationStoreConflict,
    AutomationStoreInvalid,
    AutomationStoreNotFound,
    OperatorAutomationRepository,
    initialize_operator_automation_schema,
)


pytestmark = [pytest.mark.regression, pytest.mark.serial]

TEST_DB_HOST = os.environ.get("COINBASE_DB_HOST", "coinbase-test-postgres")
TEST_DB_PORT = int(os.environ.get("COINBASE_DB_PORT", "9876"))
TEST_DB_NAME = os.environ.get("COINBASE_DB_NAME", "postgres")
TEST_DB_USER = os.environ.get("COINBASE_DB_USER", "postgres")
TEST_DB_PASSWORD = os.environ.get("COINBASE_DB_PASSWORD", "postgres")
_SCHEMA_PATTERN = re.compile(r"^test_operator_automation_[0-9a-f]{32}$")


def _new_database() -> PostgresDB:
    """Return an explicit test-service connection; never inherit main posture."""

    assert TEST_DB_HOST == "coinbase-test-postgres"
    assert TEST_DB_PORT == 9876
    return PostgresDB(
        host=TEST_DB_HOST,
        port=TEST_DB_PORT,
        database=TEST_DB_NAME,
        user=TEST_DB_USER,
        password=TEST_DB_PASSWORD,
    )


@dataclass
class _Harness:
    schema: str
    databases: list[PostgresDB] = field(default_factory=list)

    def repository(self) -> OperatorAutomationRepository:
        database = _new_database()
        self.databases.append(database)
        repository = OperatorAutomationRepository(database, schema=self.schema)
        repository.ensure_schema()
        return repository

    @property
    def database(self) -> PostgresDB:
        return self.databases[0]

    def rows(self, query: str, params: tuple = ()) -> list[dict]:
        return self.database.execute_query(query, params)

    def scalar(self, query: str, params: tuple = ()) -> int:
        rows = self.rows(query, params)
        return int(next(iter(rows[0].values())))


@pytest.fixture
def repository_harness() -> _Harness:
    schema = f"test_operator_automation_{uuid.uuid4().hex}"
    assert _SCHEMA_PATTERN.fullmatch(schema)
    database = _new_database()
    database.connect()
    with database.get_cursor() as cursor:
        cursor.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    harness = _Harness(schema=schema, databases=[database])
    harness.repository()
    try:
        yield harness
    finally:
        for extra_database in harness.databases[1:]:
            extra_database.disconnect()
        try:
            with database.get_cursor() as cursor:
                cursor.execute(
                    sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema))
                )
        finally:
            database.disconnect()


def _mutation(seed: str, *, payload_sha256: str | None = None) -> AutomationMutationCommand:
    return AutomationMutationCommand(
        idempotency_key=f"private-idempotency-{seed}",
        payload_sha256=payload_sha256 or hashlib.sha256(seed.encode("utf-8")).hexdigest(),
        actor_id=f"private-actor-{seed}",
        correlation_id=f"correlation-{seed}",
        operator_intent=f"operator intent {seed}",
    )


def _definition_command(
    seed: str,
    *,
    domain: OperatorAutomationDomain = OperatorAutomationDomain.SPOT,
    job_kind: OperatorAutomationJobKind = OperatorAutomationJobKind.SPOT_CAMPAIGN,
    product_ids: tuple[str, ...] = (),
    payload_sha256: str | None = None,
) -> AutomationDefinitionCreateCommand:
    base = _mutation(seed, payload_sha256=payload_sha256)
    return AutomationDefinitionCreateCommand(
        **base.__dict__,
        domain=domain,
        job_kind=job_kind,
        label=f"Automation {seed}",
        product_ids=product_ids,
    )


def _create_enabled(
    repository: OperatorAutomationRepository,
    seed: str,
    *,
    domain: OperatorAutomationDomain = OperatorAutomationDomain.SPOT,
    job_kind: OperatorAutomationJobKind = OperatorAutomationJobKind.SPOT_CAMPAIGN,
    product_ids: tuple[str, ...] = (),
    spot_single_child_plan: AutomationSpotSingleChildPlanTerms | None = None,
):
    created = repository.create_definition(
        _definition_command(
            seed,
            domain=domain,
            job_kind=job_kind,
            product_ids=product_ids,
        ),
        spot_single_child_plan=spot_single_child_plan,
    ).entity
    return repository.transition_definition(
        created.definition_id,
        "enable",
        _mutation(f"{seed}-enable"),
    ).entity


def test_schema_is_idempotent_and_persists_only_hashed_key_and_actor(
    repository_harness: _Harness,
):
    repository = repository_harness.repository()
    repository.ensure_schema()
    repository_harness.repository().ensure_schema()

    tables = {
        row["table_name"]
        for row in repository_harness.rows(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = %s ORDER BY table_name",
            (repository_harness.schema,),
        )
    }
    assert tables == {
        "automation_control_plane_state",
        "automation_definition",
        "automation_event_outbox",
        "automation_idempotency",
        "automation_run",
        "automation_spot_eligibility_attempt",
        "automation_spot_live_proof_goal",
        "automation_spot_run_execution",
        "automation_spot_single_child_plan",
    }

    created = repository.create_definition(_definition_command("hashed-only"))
    assert created.replayed is False
    columns = {
        row["column_name"]
        for row in repository_harness.rows(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = %s AND table_name = 'automation_idempotency'",
            (repository_harness.schema,),
        )
    }
    assert "idempotency_key" not in columns
    assert "actor_id" not in columns
    persisted = repository_harness.rows(
        f'SELECT idempotency_key_sha256, actor_id_sha256 FROM "{repository_harness.schema}".automation_idempotency'
    )
    assert persisted == [
        {
            "idempotency_key_sha256": hashlib.sha256(
                b"private-idempotency-hashed-only"
            ).hexdigest(),
            "actor_id_sha256": hashlib.sha256(
                b"private-actor-hashed-only"
            ).hexdigest(),
        }
    ]
    serialized = str(
        repository_harness.rows(
            f'SELECT event_json FROM "{repository_harness.schema}".automation_event_outbox'
        )
    )
    assert "private-idempotency-hashed-only" not in serialized
    assert "private-actor-hashed-only" not in serialized


def test_definition_lifecycle_schedule_due_posture_and_control_posture(
    repository_harness: _Harness,
):
    repository = repository_harness.repository()
    definition = repository.create_definition(_definition_command("lifecycle")).entity
    assert definition.lifecycle_state is OperatorAutomationDefinitionState.DRAFT
    assert definition.schedule_kind is OperatorAutomationScheduleKind.MANUAL_ONLY
    assert definition.schedule_due is False
    assert definition.due_reason == "manual_only"

    scheduled = repository.set_schedule(
        definition.definition_id,
        OperatorAutomationScheduleKind.INTERVAL_REVIEW_ONLY,
        interval_seconds=300,
        command=_mutation("lifecycle-schedule"),
    ).entity
    assert scheduled.interval_seconds == 300
    assert datetime.fromisoformat(scheduled.next_review_at) > datetime.now(timezone.utc)
    assert scheduled.due_reason == "definition_inactive"

    enabled = repository.transition_definition(
        definition.definition_id,
        "enable",
        _mutation("lifecycle-enable"),
    ).entity
    assert enabled.lifecycle_state is OperatorAutomationDefinitionState.ENABLED
    assert enabled.due_reason == "not_due"
    paused = repository.transition_definition(
        definition.definition_id,
        "pause",
        _mutation("lifecycle-pause"),
    ).entity
    assert paused.lifecycle_state is OperatorAutomationDefinitionState.PAUSED
    resumed = repository.transition_definition(
        definition.definition_id,
        "resume",
        _mutation("lifecycle-resume"),
    ).entity
    assert resumed.lifecycle_state is OperatorAutomationDefinitionState.ENABLED
    cleared = repository.clear_schedule(
        definition.definition_id,
        _mutation("lifecycle-clear"),
    ).entity
    assert cleared.schedule_kind is OperatorAutomationScheduleKind.MANUAL_ONLY
    schedule_events = repository_harness.rows(
        f'''SELECT diagnostic_code, to_state
            FROM "{repository_harness.schema}".automation_event_outbox
            WHERE definition_id = %s AND run_id IS NULL
              AND diagnostic_code LIKE 'automation_schedule_%%'
            ORDER BY recorded_at, event_id''',
        (definition.definition_id,),
    )
    assert {row["diagnostic_code"] for row in schedule_events} == {
        "automation_schedule_set",
        "automation_schedule_cleared",
    }
    clear_resource = repository_harness.rows(
        f'''SELECT resource_type
            FROM "{repository_harness.schema}".automation_idempotency
            WHERE idempotency_key_sha256 = %s''',
        (hashlib.sha256(b"private-idempotency-lifecycle-clear").hexdigest(),),
    )
    assert clear_resource == [{"resource_type": "definition_clear_schedule"}]

    control = repository.transition_control_posture(
        "pause", _mutation("control-pause")
    ).entity
    assert control.posture is OperatorAutomationControlPosture.PAUSED
    with pytest.raises(AutomationStoreConflict) as repeated_pause:
        repository.transition_control_posture(
            "pause", _mutation("control-pause-again")
        )
    assert repeated_pause.value.code == "automation_control_transition_invalid"
    assert repository.get_definition(definition.definition_id).due_reason == (
        "control_plane_not_active"
    )
    assert repository.transition_control_posture(
        "resume", _mutation("control-resume")
    ).entity.posture is OperatorAutomationControlPosture.ACTIVE
    assert repository.transition_control_posture(
        "drain", _mutation("control-drain")
    ).entity.posture is OperatorAutomationControlPosture.DRAINING
    assert repository.transition_control_posture(
        "shutdown", _mutation("control-shutdown")
    ).entity.posture is OperatorAutomationControlPosture.SHUTDOWN
    with pytest.raises(AutomationStoreConflict) as drain_after_shutdown:
        repository.transition_control_posture(
            "drain", _mutation("control-drain-after-shutdown")
        )
    assert drain_after_shutdown.value.code == "automation_control_transition_invalid"
    assert repository.transition_control_posture(
        "resume", _mutation("control-restart")
    ).entity.posture is OperatorAutomationControlPosture.ACTIVE

    definition_events = repository.list_definition_events(
        definition.definition_id,
        limit=50,
        offset=0,
    )
    assert definition_events.total >= 6
    assert all(
        event.definition_id == definition.definition_id
        for event in definition_events.items
    )
    assert all(event.audit_id and event.correlation_id for event in definition_events.items)

    control_events = repository.list_control_events(limit=50, offset=0)
    assert [event.diagnostic_code for event in control_events.items] == [
        "automation_control_pause",
        "automation_control_resume",
        "automation_control_drain",
        "automation_control_shutdown",
        "automation_control_resume",
    ]


def test_exact_replay_returns_original_entity_and_payload_drift_conflicts(
    repository_harness: _Harness,
):
    repository = repository_harness.repository()
    command = _definition_command("replay")
    first = repository.create_definition(command)
    replay = repository.create_definition(command)
    assert replay.replayed is True
    assert replay.entity == first.entity

    with pytest.raises(AutomationStoreConflict) as conflict:
        repository.create_definition(
            _definition_command("replay", payload_sha256="f" * 64)
        )
    assert conflict.value.code == "automation_idempotency_conflict"
    assert repository_harness.scalar(
        f'SELECT COUNT(*) FROM "{repository_harness.schema}".automation_definition'
    ) == 1


def test_exact_replay_rejects_changed_correlation_id(
    repository_harness: _Harness,
):
    repository = repository_harness.repository()
    command = _definition_command("correlation-bound-replay")
    repository.create_definition(command)

    with pytest.raises(AutomationStoreConflict) as conflict:
        repository.create_definition(
            AutomationDefinitionCreateCommand(
                **{
                    **command.__dict__,
                    "correlation_id": "correlation-changed-on-replay",
                }
            )
        )

    assert conflict.value.code == "automation_idempotency_conflict"
    assert repository_harness.scalar(
        f'SELECT COUNT(*) FROM "{repository_harness.schema}".automation_definition'
    ) == 1


def test_concurrent_one_shot_claim_has_exactly_one_winner(
    repository_harness: _Harness,
):
    repository = repository_harness.repository()
    definition = _create_enabled(repository, "claim-race")
    contenders = [repository_harness.repository(), repository_harness.repository()]
    barrier = threading.Barrier(2)
    successes = []
    conflicts = []
    unexpected = []
    result_lock = threading.Lock()

    def claim(index: int) -> None:
        barrier.wait()
        try:
            result = contenders[index].claim_one_shot_run(
                definition.definition_id,
                _mutation(f"claim-race-{index}"),
            )
            with result_lock:
                successes.append(result)
        except AutomationStoreConflict as exc:
            with result_lock:
                conflicts.append(exc)
        except BaseException as exc:  # pragma: no cover - diagnostic capture
            with result_lock:
                unexpected.append(exc)

    threads = [threading.Thread(target=claim, args=(index,)) for index in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert all(not thread.is_alive() for thread in threads)
    assert unexpected == []
    assert len(successes) == 1
    assert len(conflicts) == 1
    assert conflicts[0].code == "automation_run_in_progress"
    assert repository_harness.scalar(
        f'SELECT COUNT(*) FROM "{repository_harness.schema}".automation_run'
    ) == 1


def test_spot_single_child_goal_claim_survives_blocked_for_the_only_definition(
    repository_harness: _Harness,
):
    repository = repository_harness.repository()
    definition = _create_enabled(
        repository,
        "spot-goal-claim",
        product_ids=("BTC-USDC",),
        spot_single_child_plan=_spot_plan_terms(),
    )
    winner = repository.claim_one_shot_run(
        definition.definition_id,
        _mutation("spot-goal-claim-run"),
    ).entity
    blocked = repository.transition_run(
        winner.run_id,
        OperatorAutomationRunState.BLOCKED,
        diagnostic_code="automation_run_blocked",
        command=_mutation("spot-goal-claim-winner-blocked"),
    ).entity
    assert blocked.state is OperatorAutomationRunState.BLOCKED
    assert repository.has_spot_single_child_run() is True

    with pytest.raises(AutomationStoreConflict) as after_blocked:
        repository.claim_one_shot_run(
            definition.definition_id,
            _mutation("spot-goal-claim-after-blocked"),
        )
    assert after_blocked.value.code == "automation_spot_goal_run_already_claimed"
    assert repository_harness.scalar(
        f'SELECT COUNT(*) FROM "{repository_harness.schema}".automation_run'
    ) == 1


def test_goal_run_claim_does_not_change_generic_planless_automation_behavior(
    repository_harness: _Harness,
):
    repository = repository_harness.repository()
    definitions = [
        _create_enabled(
            repository,
            f"generic-goal-run-{index}",
            job_kind=OperatorAutomationJobKind.SPOT_SWEEP,
        )
        for index in range(2)
    ]

    runs = [
        repository.claim_one_shot_run(
            definition.definition_id,
            _mutation(f"generic-goal-run-claim-{index}"),
        ).entity
        for index, definition in enumerate(definitions)
    ]

    assert len({run.run_id for run in runs}) == 2
    assert repository.has_spot_single_child_run() is False


def test_events_are_append_only_and_carry_sanitized_audit_bindings(
    repository_harness: _Harness,
):
    repository = repository_harness.repository()
    definition = _create_enabled(repository, "events")
    run = repository.claim_one_shot_run(
        definition.definition_id, _mutation("events-claim")
    ).entity
    events = repository.list_run_events(run.run_id, limit=20, offset=0)
    assert events.total == 1
    assert events.items[0].to_state is OperatorAutomationRunState.CLAIMED
    assert events.items[0].diagnostic_code == "one_shot_run_claimed"
    assert events.items[0].audit_id
    assert events.items[0].idempotency_key_sha256 == hashlib.sha256(
        b"private-idempotency-events-claim"
    ).hexdigest()

    with pytest.raises(psycopg2.errors.RaiseException):
        repository_harness.database.execute_update(
            f'UPDATE "{repository_harness.schema}".automation_event_outbox '
            "SET diagnostic_code = 'changed' WHERE event_id = %s",
            (events.items[0].event_id,),
        )
    with pytest.raises(psycopg2.errors.RaiseException):
        repository_harness.database.execute_update(
            f'DELETE FROM "{repository_harness.schema}".automation_event_outbox '
            "WHERE event_id = %s",
            (events.items[0].event_id,),
        )
    assert repository.list_run_events(run.run_id, limit=20, offset=0).items == (
        events.items
    )

    unknown_run_id = str(uuid.uuid4())
    with pytest.raises(AutomationStoreNotFound) as unknown:
        repository.list_run_events(unknown_run_id, limit=20, offset=0)
    assert unknown.value.code == "automation_run_not_found"


def test_blocked_spot_authorization_is_idempotently_bound_and_audited_without_calls(
    repository_harness: _Harness,
):
    repository = repository_harness.repository()
    _, plan, run = _prepare_spot_run(repository, "spot-source-gate-audit")
    blocked = repository.transition_run(
        run.run_id,
        OperatorAutomationRunState.BLOCKED,
        diagnostic_code="automation_active_order_catalog_read_not_authorized",
        command=_mutation("spot-source-gate-initial-block"),
    ).entity
    before = repository.list_run_events(run.run_id, limit=20, offset=0)
    command = _mutation("spot-source-gate-authorization")

    first = repository.audit_spot_source_gate_authorization(
        run.run_id,
        expected_plan_sha256=plan.plan_sha256,
        command=command,
    )
    replay = repository.audit_spot_source_gate_authorization(
        run.run_id,
        expected_plan_sha256=plan.plan_sha256,
        command=command,
    )

    assert first.replayed is False
    assert replay.replayed is True
    assert replay.entity == first.entity == blocked
    assert replay.audit_id == first.audit_id
    current = repository.get_run(run.run_id)
    assert current == blocked
    assert current.coinbase_api_call_count == 0
    assert current.create_call_count == 0
    assert current.cancel_call_count == 0
    events = repository.list_run_events(run.run_id, limit=20, offset=0)
    assert events.total == before.total + 1
    audit_event = events.items[-1]
    assert audit_event.from_state is OperatorAutomationRunState.BLOCKED
    assert audit_event.to_state is OperatorAutomationRunState.BLOCKED
    assert audit_event.diagnostic_code == (
        "automation_active_order_catalog_read_not_authorized"
    )
    assert audit_event.idempotency_key_sha256 == hashlib.sha256(
        command.idempotency_key.encode("utf-8")
    ).hexdigest()

    with pytest.raises(AutomationStoreConflict) as changed_payload:
        repository.audit_spot_source_gate_authorization(
            run.run_id,
            expected_plan_sha256="f" * 64,
            command=_mutation(
                "spot-source-gate-authorization",
                payload_sha256="f" * 64,
            ),
        )
    assert changed_payload.value.code == "automation_idempotency_conflict"
    assert repository.list_run_events(
        run.run_id,
        limit=20,
        offset=0,
    ).total == events.total


def test_restart_recovery_terminally_blocks_pre_invocation_and_quarantines_started_run(
    repository_harness: _Harness,
):
    repository = repository_harness.repository()
    definition = _create_enabled(repository, "recovery")
    first = repository.claim_one_shot_run(
        definition.definition_id, _mutation("recovery-first")
    ).entity
    first = repository.transition_run(
        first.run_id,
        OperatorAutomationRunState.PREPARING,
        diagnostic_code="preparing",
        command=_mutation("recovery-preparing"),
    ).entity

    restarted = repository_harness.repository()
    recovered = restarted.recover_runs_after_restart()
    assert [record.run_id for record in recovered] == [first.run_id]
    assert recovered[0].state is OperatorAutomationRunState.BLOCKED
    assert recovered[0].diagnostic_code == "restart_pre_invocation_blocked"
    assert recovered[0].live_attempt_consumed is False
    assert restarted.recover_runs_after_restart() == ()

    second = restarted.claim_one_shot_run(
        definition.definition_id, _mutation("recovery-second")
    ).entity
    second = restarted.transition_run(
        second.run_id,
        OperatorAutomationRunState.PREPARING,
        diagnostic_code="preparing",
        command=_mutation("recovery-second-preparing"),
    ).entity
    second = restarted.transition_run(
        second.run_id,
        OperatorAutomationRunState.AWAITING_OPERATOR_AUTHORIZATION,
        diagnostic_code="awaiting_operator_authorization",
        command=_mutation("recovery-second-awaiting"),
    ).entity
    restarted.transition_run(
        second.run_id,
        OperatorAutomationRunState.INVOCATION_STARTED,
        diagnostic_code="invocation_started",
        command=_mutation("recovery-second-invoked"),
    )

    after_invocation_restart = repository_harness.repository()
    quarantined = after_invocation_restart.recover_runs_after_restart()
    assert [record.run_id for record in quarantined] == [second.run_id]
    assert quarantined[0].state is OperatorAutomationRunState.UNKNOWN_CONSUMED
    assert quarantined[0].diagnostic_code == "restart_unknown_consumed"
    assert after_invocation_restart.recover_runs_after_restart() == ()


def test_definition_and_run_pagination_filters_are_backend_owned(
    repository_harness: _Harness,
):
    repository = repository_harness.repository()
    campaign = _create_enabled(repository, "page-campaign")
    sweep = _create_enabled(
        repository,
        "page-sweep",
        job_kind=OperatorAutomationJobKind.SPOT_SWEEP,
    )
    follow_up = repository.create_definition(
        _definition_command(
            "page-follow-up",
            domain=OperatorAutomationDomain.ORDERS,
            job_kind=OperatorAutomationJobKind.FOLLOW_UP,
        )
    ).entity

    first_page = repository.list_definitions(limit=2, offset=0)
    second_page = repository.list_definitions(limit=2, offset=2)
    assert first_page.total == 3
    assert len(first_page.items) == 2
    assert len(second_page.items) == 1
    assert repository.list_definitions(
        domain=OperatorAutomationDomain.ORDERS,
        limit=10,
        offset=0,
    ).items == (follow_up,)
    assert repository.list_definitions(
        job_kind=OperatorAutomationJobKind.SPOT_SWEEP,
        lifecycle_state=OperatorAutomationDefinitionState.ENABLED,
        limit=10,
        offset=0,
    ).items == (sweep,)

    run = repository.claim_one_shot_run(
        campaign.definition_id, _mutation("page-run")
    ).entity
    page = repository.list_runs(
        definition_id=campaign.definition_id,
        state=OperatorAutomationRunState.CLAIMED,
        limit=10,
        offset=0,
    )
    assert page.total == 1
    assert page.items == (run,)


def test_control_posture_and_definition_state_fail_closed_for_run_claim(
    repository_harness: _Harness,
):
    repository = repository_harness.repository()
    draft = repository.create_definition(_definition_command("blocked-draft")).entity
    with pytest.raises(AutomationStoreConflict) as draft_conflict:
        repository.claim_one_shot_run(draft.definition_id, _mutation("draft-run"))
    assert draft_conflict.value.code == "automation_definition_not_enabled"

    enabled = _create_enabled(repository, "blocked-control")
    repository.transition_control_posture("pause", _mutation("blocked-pause"))
    with pytest.raises(AutomationStoreConflict) as posture_conflict:
        repository.claim_one_shot_run(
            enabled.definition_id, _mutation("blocked-control-run")
        )
    assert posture_conflict.value.code == "automation_control_plane_not_active"
    assert repository.get_control_posture().posture is (
        OperatorAutomationControlPosture.PAUSED
    )


def test_startup_initialization_installs_schema_then_recovers_runs(monkeypatch):
    events: list[str] = []

    class _Repository:
        def ensure_schema(self) -> None:
            events.append("schema")

        def recover_runs_after_restart(self) -> tuple:
            events.append("recovery")
            return ()

    monkeypatch.setattr(
        "database.operator_automation.get_default_operator_automation_repository",
        lambda: _Repository(),
    )

    initialize_operator_automation_schema()

    assert events == ["schema", "recovery"]


def _spot_plan_terms(**overrides: object) -> AutomationSpotSingleChildPlanTerms:
    values: dict[str, object] = {
        "portfolio_id_sha256": hashlib.sha256(
            b"private-test-portfolio-uuid"
        ).hexdigest(),
        "product_id": "BTC-USDC",
        "side": "BUY",
        "base_size": "0.00002",
        "limit_price": "50000",
        "submitted_notional_usdc": "1.00",
        "possible_execution_notional_usdc": "1.00",
        "max_submitted_notional_usdc": "3.10",
        "max_possible_execution_notional_usdc": "1.00",
        "post_only": False,
    }
    values.update(overrides)
    return AutomationSpotSingleChildPlanTerms(
        **values,
    )


def test_plan_bearing_definition_create_is_atomic_exactly_replayable_and_concurrent(
    repository_harness: _Harness,
):
    command = _definition_command(
        "atomic-spot-create",
        product_ids=("BTC-USDC",),
    )
    barrier = threading.Barrier(2)
    results: list = []
    failures: list[Exception] = []
    result_lock = threading.Lock()

    def create() -> None:
        repository = repository_harness.repository()
        barrier.wait()
        try:
            result = repository.create_definition(
                command,
                spot_single_child_plan=_spot_plan_terms(),
            )
            with result_lock:
                results.append(result)
        except Exception as exc:  # pragma: no cover - asserted below
            with result_lock:
                failures.append(exc)

    threads = [threading.Thread(target=create) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert all(not thread.is_alive() for thread in threads)
    assert failures == []
    assert len(results) == 2
    assert sorted(result.replayed for result in results) == [False, True]
    assert len({result.entity.definition_id for result in results}) == 1
    definition = results[0].entity
    plan = repository_harness.repository().get_spot_single_child_plan(
        definition.definition_id,
        definition.revision,
    )
    assert plan is not None
    assert plan.product_id == "BTC-USDC"
    assert plan.definition_revision == 1
    assert repository_harness.scalar(
        f'SELECT COUNT(*) FROM "{repository_harness.schema}".automation_definition'
    ) == 1
    assert repository_harness.scalar(
        f'SELECT COUNT(*) FROM "{repository_harness.schema}".automation_spot_single_child_plan'
    ) == 1


def test_goal_allows_only_one_distinct_plan_bearing_definition_under_concurrency(
    repository_harness: _Harness,
):
    contenders = [
        repository_harness.repository(),
        repository_harness.repository(),
    ]
    barrier = threading.Barrier(2)
    successes: list = []
    conflicts: list[AutomationStoreConflict] = []
    unexpected: list[BaseException] = []
    result_lock = threading.Lock()

    def create(index: int) -> None:
        barrier.wait()
        try:
            result = contenders[index].create_definition(
                _definition_command(
                    f"atomic-distinct-spot-create-{index}",
                    product_ids=("BTC-USDC",),
                ),
                spot_single_child_plan=_spot_plan_terms(),
            )
            with result_lock:
                successes.append(result)
        except AutomationStoreConflict as exc:
            with result_lock:
                conflicts.append(exc)
        except BaseException as exc:  # pragma: no cover - diagnostic capture
            with result_lock:
                unexpected.append(exc)

    threads = [threading.Thread(target=create, args=(index,)) for index in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert all(not thread.is_alive() for thread in threads)
    assert unexpected == []
    assert len(successes) == 1
    assert [conflict.code for conflict in conflicts] == [
        "automation_spot_single_child_definition_already_exists"
    ]
    assert repository_harness.scalar(
        f'SELECT COUNT(*) FROM "{repository_harness.schema}".automation_definition'
    ) == 1
    assert repository_harness.scalar(
        f'SELECT COUNT(*) FROM "{repository_harness.schema}".automation_spot_single_child_plan'
    ) == 1


def test_plan_bearing_definition_create_rolls_back_every_record_when_plan_insert_fails(
    repository_harness: _Harness,
    monkeypatch: pytest.MonkeyPatch,
):
    repository = repository_harness.repository()

    def fail_plan_insert(*_args, **_kwargs):
        raise RuntimeError("synthetic_plan_insert_failure")

    monkeypatch.setattr(
        repository,
        "_insert_spot_single_child_plan",
        fail_plan_insert,
    )

    with pytest.raises(RuntimeError, match="synthetic_plan_insert_failure"):
        repository.create_definition(
            _definition_command(
                "atomic-spot-create-rollback",
                product_ids=("BTC-USDC",),
            ),
            spot_single_child_plan=_spot_plan_terms(),
        )

    for table in (
        "automation_definition",
        "automation_spot_single_child_plan",
        "automation_event_outbox",
        "automation_idempotency",
    ):
        assert repository_harness.scalar(
            f'SELECT COUNT(*) FROM "{repository_harness.schema}".{table}'
        ) == 0


def test_plan_is_carried_atomically_through_definition_and_schedule_revisions(
    repository_harness: _Harness,
):
    repository = repository_harness.repository()
    created = repository.create_definition(
        _definition_command(
            "atomic-spot-revision",
            product_ids=("BTC-USDC",),
        ),
        spot_single_child_plan=_spot_plan_terms(),
    ).entity
    original = repository.get_spot_single_child_plan(
        created.definition_id,
        created.revision,
    )
    assert original is not None

    transition_command = _mutation("atomic-spot-revision-enable")
    enabled_result = repository.transition_definition(
        created.definition_id,
        "enable",
        transition_command,
    )
    assert repository.transition_definition(
        created.definition_id,
        "enable",
        transition_command,
    ).replayed is True
    scheduled = repository.set_schedule(
        created.definition_id,
        OperatorAutomationScheduleKind.INTERVAL_REVIEW_ONLY,
        interval_seconds=300,
        command=_mutation("atomic-spot-revision-schedule"),
    ).entity
    cleared = repository.clear_schedule(
        created.definition_id,
        _mutation("atomic-spot-revision-clear"),
    ).entity

    revisions = (created, enabled_result.entity, scheduled, cleared)
    plans = tuple(
        repository.get_spot_single_child_plan(item.definition_id, item.revision)
        for item in revisions
    )
    assert all(plan is not None for plan in plans)
    assert [item.revision for item in revisions] == [1, 2, 3, 4]
    assert len({plan.plan_sha256 for plan in plans if plan is not None}) == 4
    assert all(
        plan is not None
        and plan.product_id == original.product_id
        and plan.side == original.side
        and plan.base_size == original.base_size
        and plan.limit_price == original.limit_price
        and plan.submitted_notional_usdc == original.submitted_notional_usdc
        and plan.possible_execution_notional_usdc
        == original.possible_execution_notional_usdc
        for plan in plans
    )

    generic = repository.create_definition(
        _definition_command(
            "atomic-planless-generic",
            job_kind=OperatorAutomationJobKind.SPOT_SWEEP,
            product_ids=("BTC-USDC",),
        )
    ).entity
    generic_enabled = repository.transition_definition(
        generic.definition_id,
        "enable",
        _mutation("atomic-planless-generic-enable"),
    ).entity
    assert repository.get_spot_single_child_plan(
        generic.definition_id,
        generic_enabled.revision,
    ) is None


def test_plan_bearing_revision_rolls_back_definition_event_and_idempotency_on_carry_failure(
    repository_harness: _Harness,
    monkeypatch: pytest.MonkeyPatch,
):
    repository = repository_harness.repository()
    created = repository.create_definition(
        _definition_command(
            "atomic-spot-revision-rollback",
            product_ids=("BTC-USDC",),
        ),
        spot_single_child_plan=_spot_plan_terms(),
    ).entity
    event_count = repository_harness.scalar(
        f'SELECT COUNT(*) FROM "{repository_harness.schema}".automation_event_outbox'
    )
    idempotency_count = repository_harness.scalar(
        f'SELECT COUNT(*) FROM "{repository_harness.schema}".automation_idempotency'
    )

    def fail_plan_insert(*_args, **_kwargs):
        raise RuntimeError("synthetic_plan_carry_failure")

    monkeypatch.setattr(
        repository,
        "_insert_spot_single_child_plan",
        fail_plan_insert,
    )
    with pytest.raises(RuntimeError, match="synthetic_plan_carry_failure"):
        repository.transition_definition(
            created.definition_id,
            "enable",
            _mutation("atomic-spot-revision-rollback-enable"),
        )

    persisted = repository.get_definition(created.definition_id)
    assert persisted is not None
    assert persisted.revision == 1
    assert persisted.lifecycle_state is OperatorAutomationDefinitionState.DRAFT
    assert repository.get_spot_single_child_plan(created.definition_id, 2) is None
    assert repository_harness.scalar(
        f'SELECT COUNT(*) FROM "{repository_harness.schema}".automation_event_outbox'
    ) == event_count
    assert repository_harness.scalar(
        f'SELECT COUNT(*) FROM "{repository_harness.schema}".automation_idempotency'
    ) == idempotency_count


def _prepare_spot_run(
    repository: OperatorAutomationRepository,
    seed: str,
):
    definition = _create_enabled(
        repository,
        seed,
        product_ids=("BTC-USDC",),
        spot_single_child_plan=_spot_plan_terms(),
    )
    plan = repository.get_spot_single_child_plan(
        definition.definition_id,
        definition.revision,
    )
    assert plan is not None
    run = repository.claim_one_shot_run(
        definition.definition_id,
        _mutation(f"{seed}-run"),
    ).entity
    assert run.definition_revision == definition.revision
    run = repository.transition_run(
        run.run_id,
        OperatorAutomationRunState.PREPARING,
        diagnostic_code="preparing",
        command=_mutation(f"{seed}-preparing"),
    ).entity
    return definition, plan, run


def _complete_eligible_cycle(
    repository: OperatorAutomationRepository,
    run_id: str,
    seed: str,
    *,
    cycle_number: int = 1,
) -> None:
    run = repository.get_run(run_id)
    assert run is not None and run.definition_revision is not None
    plan = repository.get_spot_single_child_plan(
        run.definition_id,
        run.definition_revision,
    )
    assert plan is not None
    for index, category in enumerate(AUTOMATION_SPOT_ELIGIBILITY_CATEGORIES):
        started = repository.start_spot_eligibility_attempt(
            run_id,
            cycle_number=cycle_number,
            category=category,
            command=_mutation(f"{seed}-{index}-start"),
        )
        assert started.entity.outcome is None
        assert started.entity.allowance_consumed is True
        finalized = repository.finalize_spot_eligibility_attempt(
            run_id,
            cycle_number=cycle_number,
            category=category,
            outcome="SUCCEEDED",
            eligible=True,
            coinbase_api_call_count=1,
            call_count_exact=True,
            portfolio_id_sha256=(
                plan.portfolio_id_sha256
                if category == "PORTFOLIO_CATALOG"
                else None
            ),
            command=_mutation(f"{seed}-{index}-finish"),
        )
        assert finalized.entity.outcome == "SUCCEEDED"
        assert finalized.entity.eligible is True


def _await_spot_authorization(
    repository: OperatorAutomationRepository,
    run_id: str,
    seed: str,
):
    return repository.transition_run(
        run_id,
        OperatorAutomationRunState.AWAITING_OPERATOR_AUTHORIZATION,
        diagnostic_code="awaiting_operator_authorization",
        command=_mutation(f"{seed}-awaiting"),
    ).entity


def test_spot_single_child_plan_has_only_atomic_definition_write_path_and_is_immutable(
    repository_harness: _Harness,
):
    repository = repository_harness.repository()
    with pytest.raises(AutomationStoreInvalid) as wrong_product:
        repository.create_definition(
            _definition_command(
                "spot-plan-wrong-product",
                product_ids=("BTC-USDC",),
            ),
            spot_single_child_plan=_spot_plan_terms(product_id="ETH-USDC"),
        )
    assert wrong_product.value.code == "automation_spot_plan_product_blocked"

    with pytest.raises(AutomationStoreInvalid) as post_only_blocked:
        repository.create_definition(
            _definition_command(
                "spot-plan-post-only",
                product_ids=("BTC-USDC",),
            ),
            spot_single_child_plan=_spot_plan_terms(post_only=True),
        )
    assert post_only_blocked.value.code == "automation_spot_plan_post_only_invalid"

    with pytest.raises(AutomationStoreInvalid) as wrong_job_kind:
        repository.create_definition(
            _definition_command(
                "spot-plan-sweep-blocked",
                job_kind=OperatorAutomationJobKind.SPOT_SWEEP,
                product_ids=("BTC-USDC",),
            ),
            spot_single_child_plan=_spot_plan_terms(),
        )
    assert wrong_job_kind.value.code == "automation_spot_plan_definition_mismatch"

    command = _definition_command(
        "spot-plan",
        product_ids=("BTC-USDC",),
    )
    created_result = repository.create_definition(
        command,
        spot_single_child_plan=_spot_plan_terms(),
    )
    assert created_result.replayed is False
    definition = created_result.entity
    plan = repository.get_spot_single_child_plan(
        definition.definition_id,
        definition.revision,
    )
    assert plan is not None
    assert plan.product_id == "BTC-USDC"
    assert plan.submitted_notional_usdc == "1"
    assert plan.possible_execution_notional_usdc == "1"
    assert plan.max_submitted_notional_usdc == "3.1"
    assert plan.max_possible_execution_notional_usdc == "1"
    assert re.fullmatch(r"[0-9a-f]{64}", plan.plan_sha256)
    replay = repository.create_definition(
        command,
        spot_single_child_plan=_spot_plan_terms(),
    )
    assert replay.replayed is True
    assert replay.entity == definition
    assert not hasattr(repository, "create_spot_single_child_plan")

    persisted = str(
        repository_harness.rows(
            f'SELECT * FROM "{repository_harness.schema}".automation_spot_single_child_plan'
        )
    )
    assert "private-test-portfolio-uuid" not in persisted
    assert _spot_plan_terms().portfolio_id_sha256 in persisted

    with pytest.raises(psycopg2.errors.RaiseException):
        repository_harness.database.execute_update(
            f'UPDATE "{repository_harness.schema}".automation_spot_single_child_plan '
            "SET side = 'SELL' WHERE definition_id = %s AND definition_revision = %s",
            (definition.definition_id, definition.revision),
        )
    with pytest.raises(psycopg2.errors.RaiseException):
        repository_harness.database.execute_update(
            f'DELETE FROM "{repository_harness.schema}".automation_spot_single_child_plan '
            "WHERE definition_id = %s AND definition_revision = %s",
            (definition.definition_id, definition.revision),
        )

    with pytest.raises(AutomationStoreConflict) as second_plan_definition:
        repository.create_definition(
            _definition_command(
                "spot-plan-second-campaign-blocked",
                product_ids=("BTC-USDC",),
            ),
            spot_single_child_plan=_spot_plan_terms(),
        )
    assert second_plan_definition.value.code == (
        "automation_spot_single_child_definition_already_exists"
    )


def test_spot_eligibility_attempts_are_cycle_and_category_bounded(
    repository_harness: _Harness,
):
    repository = repository_harness.repository()
    _, _, run = _prepare_spot_run(repository, "spot-eligibility")
    category = AUTOMATION_SPOT_ELIGIBILITY_CATEGORIES[0]
    command = _mutation("spot-eligibility-start")

    started = repository.start_spot_eligibility_attempt(
        run.run_id,
        cycle_number=1,
        category=category,
        command=command,
    )
    replay = repository.start_spot_eligibility_attempt(
        run.run_id,
        cycle_number=1,
        category=category,
        command=command,
    )
    assert replay.replayed is True
    assert replay.entity == started.entity
    with pytest.raises(AutomationStoreConflict) as duplicate:
        repository.start_spot_eligibility_attempt(
            run.run_id,
            cycle_number=1,
            category=category,
            command=_mutation("spot-eligibility-duplicate"),
        )
    assert duplicate.value.code == "automation_spot_eligibility_category_consumed"

    terminal = repository.finalize_spot_eligibility_attempt(
        run.run_id,
        cycle_number=1,
        category=category,
        outcome="UNKNOWN",
        eligible=False,
        coinbase_api_call_count=None,
        call_count_exact=False,
        portfolio_id_sha256=None,
        command=_mutation("spot-eligibility-finish"),
    ).entity
    assert terminal.outcome == "UNKNOWN"
    assert terminal.coinbase_api_call_count is None
    assert terminal.call_count_exact is False

    with pytest.raises(AutomationStoreInvalid) as cycle_limit:
        repository.start_spot_eligibility_attempt(
            run.run_id,
            cycle_number=11,
            category=category,
            command=_mutation("spot-eligibility-cycle-11"),
        )
    assert cycle_limit.value.code == "automation_spot_eligibility_cycle_invalid"
    with pytest.raises(AutomationStoreInvalid) as category_invalid:
        repository.start_spot_eligibility_attempt(
            run.run_id,
            cycle_number=2,
            category="UNAPPROVED_READ",
            command=_mutation("spot-eligibility-category-invalid"),
        )
    assert category_invalid.value.code == "automation_spot_eligibility_category_invalid"


def test_portfolio_catalog_proof_is_exactly_bound_to_the_run_plan(
    repository_harness: _Harness,
):
    repository = repository_harness.repository()
    _, plan, run = _prepare_spot_run(repository, "spot-catalog-binding")
    category = "PORTFOLIO_CATALOG"

    def start(seed: str, cycle: int) -> None:
        repository.start_spot_eligibility_attempt(
            run.run_id,
            cycle_number=cycle,
            category=category,
            command=_mutation(f"{seed}-start"),
        )

    start("catalog-missing", 1)
    with pytest.raises(AutomationStoreInvalid) as missing:
        repository.finalize_spot_eligibility_attempt(
            run.run_id,
            cycle_number=1,
            category=category,
            outcome="SUCCEEDED",
            eligible=True,
            coinbase_api_call_count=1,
            call_count_exact=True,
            portfolio_id_sha256=None,
            command=_mutation("catalog-missing-finish"),
        )
    assert missing.value.code == "automation_spot_portfolio_binding_required"

    with pytest.raises(AutomationStoreConflict) as mismatch:
        repository.finalize_spot_eligibility_attempt(
            run.run_id,
            cycle_number=1,
            category=category,
            outcome="SUCCEEDED",
            eligible=True,
            coinbase_api_call_count=1,
            call_count_exact=True,
            portfolio_id_sha256="f" * 64,
            command=_mutation("catalog-mismatch-finish"),
        )
    assert mismatch.value.code == "automation_spot_portfolio_binding_mismatch"

    bound = repository.finalize_spot_eligibility_attempt(
        run.run_id,
        cycle_number=1,
        category=category,
        outcome="SUCCEEDED",
        eligible=True,
        coinbase_api_call_count=1,
        call_count_exact=True,
        portfolio_id_sha256=plan.portfolio_id_sha256,
        command=_mutation("catalog-bound-finish"),
    ).entity
    assert bound.portfolio_id_sha256 == plan.portfolio_id_sha256

    other_category = "API_KEY_PERMISSIONS"
    repository.start_spot_eligibility_attempt(
        run.run_id,
        cycle_number=1,
        category=other_category,
        command=_mutation("other-binding-start"),
    )
    with pytest.raises(AutomationStoreInvalid) as unrelated:
        repository.finalize_spot_eligibility_attempt(
            run.run_id,
            cycle_number=1,
            category=other_category,
            outcome="SUCCEEDED",
            eligible=True,
            coinbase_api_call_count=1,
            call_count_exact=True,
            portfolio_id_sha256=plan.portfolio_id_sha256,
            command=_mutation("other-binding-finish"),
        )
    assert unrelated.value.code == "automation_spot_portfolio_binding_forbidden"


def test_schema_migrates_legacy_catalog_attempt_without_inventing_binding(
    repository_harness: _Harness,
):
    repository = repository_harness.repository()
    _, _, run = _prepare_spot_run(repository, "spot-catalog-migration")
    category = "PORTFOLIO_CATALOG"
    repository.start_spot_eligibility_attempt(
        run.run_id,
        cycle_number=1,
        category=category,
        command=_mutation("catalog-migration-start"),
    )
    repository_harness.database.execute_update(
        f'ALTER TABLE "{repository_harness.schema}".automation_spot_eligibility_attempt '
        "DROP COLUMN portfolio_id_sha256"
    )
    repository_harness.database.execute_update(
        f'UPDATE "{repository_harness.schema}".automation_spot_eligibility_attempt '
        "SET outcome = 'SUCCEEDED', eligible = TRUE, "
        "coinbase_api_call_count = 1, call_count_exact = TRUE, "
        "diagnostic_code = 'automation_spot_eligibility_succeeded', "
        "finalized_at = NOW() WHERE run_id = %s AND cycle_number = 1 "
        "AND category = %s",
        (run.run_id, category),
    )

    repository.ensure_schema()

    migrated = repository.list_spot_eligibility_attempts(
        run.run_id,
        cycle_number=1,
    )[0]
    assert migrated.outcome == "SUCCEEDED"
    assert migrated.eligible is True
    assert migrated.portfolio_id_sha256 is None


@pytest.mark.parametrize(
    ("outcome", "child_terminal", "call_count", "call_count_exact", "run_state"),
    [
        ("ACCEPTED", True, 1, True, OperatorAutomationRunState.TERMINAL),
        ("REJECTED", False, 0, True, OperatorAutomationRunState.TERMINAL),
        ("REJECTED", False, 1, True, OperatorAutomationRunState.TERMINAL),
        ("UNKNOWN", None, None, False, OperatorAutomationRunState.UNKNOWN_CONSUMED),
    ],
)
def test_spot_create_invocation_consumes_once_and_finalizes_value_blind_accounting(
    repository_harness: _Harness,
    outcome: str,
    child_terminal: bool | None,
    call_count: int | None,
    call_count_exact: bool,
    run_state: OperatorAutomationRunState,
):
    repository = repository_harness.repository()
    _, plan, run = _prepare_spot_run(repository, f"spot-create-{outcome.lower()}")
    _complete_eligible_cycle(
        repository,
        run.run_id,
        f"spot-create-{outcome.lower()}-eligibility",
    )
    _await_spot_authorization(repository, run.run_id, f"spot-create-{outcome.lower()}")

    started = repository.start_spot_create_invocation(
        run.run_id,
        eligibility_cycle=1,
        command=_mutation(f"spot-create-{outcome.lower()}-start"),
    )
    assert started.entity.plan_sha256 == plan.plan_sha256
    assert started.entity.create_allowance_consumed is True
    assert started.entity.create_outcome is None
    assert started.entity.create_call_count is None
    assert started.entity.create_call_count_exact is False
    assert uuid.UUID(started.entity.client_order_id).version == 5
    bound_run = repository.get_run(run.run_id)
    assert bound_run is not None
    assert bound_run.state is OperatorAutomationRunState.INVOCATION_STARTED
    assert bound_run.client_order_id == started.entity.client_order_id
    assert bound_run.live_attempt_consumed is True
    assert bound_run.create_call_count == 1
    assert repository.get_spot_live_proof_goal().create_allowance_consumed is True

    finalized = repository.finalize_spot_create_invocation(
        run.run_id,
        outcome=outcome,
        child_terminal=child_terminal,
        coinbase_api_call_count=call_count,
        call_count_exact=call_count_exact,
        command=_mutation(f"spot-create-{outcome.lower()}-finish"),
    ).entity
    assert finalized.create_outcome == outcome
    assert finalized.create_call_count == call_count
    assert finalized.create_call_count_exact is call_count_exact
    assert repository.get_run(run.run_id).state is run_state


def test_spot_create_restart_recovery_marks_unfinalized_boundary_unknown_once(
    repository_harness: _Harness,
):
    repository = repository_harness.repository()
    _, _, run = _prepare_spot_run(repository, "spot-create-restart")
    _complete_eligible_cycle(
        repository,
        run.run_id,
        "spot-create-restart-eligibility",
    )
    _await_spot_authorization(repository, run.run_id, "spot-create-restart")
    started = repository.start_spot_create_invocation(
        run.run_id,
        eligibility_cycle=1,
        command=_mutation("spot-create-restart-start"),
    ).entity

    restarted = repository_harness.repository()
    recovered = restarted.recover_runs_after_restart()
    assert [record.run_id for record in recovered] == [run.run_id]
    execution = restarted.get_spot_run_execution(run.run_id)
    assert execution is not None
    assert execution.client_order_id == started.client_order_id
    assert execution.create_outcome == "UNKNOWN"
    assert execution.create_call_count is None
    assert execution.create_call_count_exact is False
    goal = restarted.get_spot_live_proof_goal()
    assert goal.create_outcome == "UNKNOWN"
    assert restarted.recover_runs_after_restart() == ()


def test_spot_cancel_claim_is_exact_child_single_use_and_restart_safe(
    repository_harness: _Harness,
):
    repository = repository_harness.repository()
    _, _, run = _prepare_spot_run(repository, "spot-cancel")
    _complete_eligible_cycle(repository, run.run_id, "spot-cancel-eligibility")
    _await_spot_authorization(repository, run.run_id, "spot-cancel")
    created = repository.start_spot_create_invocation(
        run.run_id,
        eligibility_cycle=1,
        command=_mutation("spot-cancel-create-start"),
    ).entity
    active = repository.finalize_spot_create_invocation(
        run.run_id,
        outcome="ACCEPTED",
        child_terminal=False,
        coinbase_api_call_count=1,
        call_count_exact=True,
        command=_mutation("spot-cancel-create-finish"),
    ).entity
    assert repository.get_run(run.run_id).state is OperatorAutomationRunState.ACTIVE

    with pytest.raises(AutomationStoreConflict) as wrong_child:
        repository.start_spot_cancel_invocation(
            run.run_id,
            client_order_id=str(uuid.uuid4()),
            command=_mutation("spot-cancel-wrong-child"),
        )
    assert wrong_child.value.code == "automation_spot_cancel_child_mismatch"
    assert repository.get_spot_live_proof_goal().cancel_allowance_consumed is False

    cancelling = repository.start_spot_cancel_invocation(
        run.run_id,
        client_order_id=created.client_order_id,
        command=_mutation("spot-cancel-start"),
    ).entity
    assert cancelling.cancel_allowance_consumed is True
    assert repository.get_run(run.run_id).cancel_call_count == 1
    terminal = repository.finalize_spot_cancel_invocation(
        run.run_id,
        outcome="ACCEPTED",
        child_terminal=True,
        coinbase_api_call_count=1,
        call_count_exact=True,
        command=_mutation("spot-cancel-finish"),
    ).entity
    assert terminal.cancel_outcome == "ACCEPTED"
    assert terminal.child_terminal is True
    assert repository.get_run(run.run_id).state is OperatorAutomationRunState.TERMINAL

    with pytest.raises(AutomationStoreConflict) as second_cancel:
        repository.start_spot_cancel_invocation(
            run.run_id,
            client_order_id=created.client_order_id,
            command=_mutation("spot-cancel-second"),
        )
    assert second_cancel.value.code == "automation_spot_cancel_allowance_consumed"


def test_spot_active_child_survives_restart_until_exact_cancel_starts(
    repository_harness: _Harness,
):
    repository = repository_harness.repository()
    _, _, run = _prepare_spot_run(repository, "spot-active-restart")
    _complete_eligible_cycle(
        repository,
        run.run_id,
        "spot-active-restart-eligibility",
    )
    _await_spot_authorization(repository, run.run_id, "spot-active-restart")
    created = repository.start_spot_create_invocation(
        run.run_id,
        eligibility_cycle=1,
        command=_mutation("spot-active-restart-create-start"),
    ).entity
    repository.finalize_spot_create_invocation(
        run.run_id,
        outcome="ACCEPTED",
        child_terminal=False,
        coinbase_api_call_count=1,
        call_count_exact=True,
        command=_mutation("spot-active-restart-create-finish"),
    )

    restarted = repository_harness.repository()
    assert restarted.recover_runs_after_restart() == ()
    active = restarted.get_run(run.run_id)
    assert active is not None
    assert active.state is OperatorAutomationRunState.ACTIVE
    assert active.diagnostic_code == "automation_spot_create_accepted_active"

    restarted.start_spot_cancel_invocation(
        run.run_id,
        client_order_id=created.client_order_id,
        command=_mutation("spot-active-restart-cancel-start"),
    )
    after_cancel_boundary = repository_harness.repository()
    recovered = after_cancel_boundary.recover_runs_after_restart()
    assert [item.run_id for item in recovered] == [run.run_id]
    assert recovered[0].state is OperatorAutomationRunState.UNKNOWN_CONSUMED
    execution = after_cancel_boundary.get_spot_run_execution(run.run_id)
    assert execution is not None
    assert execution.cancel_outcome == "UNKNOWN"
    assert execution.cancel_call_count is None
    assert execution.cancel_call_count_exact is False
