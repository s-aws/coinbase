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
    AutomationStoreConflict,
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
    payload_sha256: str | None = None,
) -> AutomationDefinitionCreateCommand:
    base = _mutation(seed, payload_sha256=payload_sha256)
    return AutomationDefinitionCreateCommand(
        **base.__dict__,
        domain=domain,
        job_kind=job_kind,
        label=f"Automation {seed}",
    )


def _create_enabled(
    repository: OperatorAutomationRepository,
    seed: str,
    *,
    domain: OperatorAutomationDomain = OperatorAutomationDomain.SPOT,
    job_kind: OperatorAutomationJobKind = OperatorAutomationJobKind.SPOT_CAMPAIGN,
):
    created = repository.create_definition(
        _definition_command(seed, domain=domain, job_kind=job_kind)
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
