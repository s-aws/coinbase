"""Real-PostgreSQL contract for the operator Automation control plane."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
import hashlib
import os
import re
import threading
import uuid

import psycopg2
from psycopg2 import sql
import pytest

from application.admin_api.operator_automation import (
    OperatorAutomationService,
    PostgresOperatorAutomationRepositoryAdapter,
)
from application.admin_api.automation_models import AutomationMutationContext
from application.admin_api.operator_spot_near_market_policy import (
    NearMarketBuyPlan,
)
from application.admin_api.operator_spot_near_market_preparation import (
    NearMarketPreparationOutcome,
    NearMarketPreparationResult,
)
from application.admin_api.operator_spot_minimum_size_policy import (
    MinimumSizeBuyPlan,
)
from application.admin_api.operator_spot_minimum_size_preparation import (
    MinimumSizePreparationOutcome,
    MinimumSizePreparationResult,
)
from core.operator_spot_minimum_size_evidence import (
    MINIMUM_SIZE_POLICY_REVISION,
    minimum_size_preparation_evidence_sha256,
)
from core.enums import (
    OperatorAutomationControlPosture,
    OperatorAutomationDefinitionState,
    OperatorAutomationDomain,
    OperatorAutomationJobKind,
    OperatorAutomationRunState,
    OperatorAutomationScheduleKind,
)
from core.operator_spot_near_market_evidence import (
    NEAR_MARKET_POLICY_REVISION,
    near_market_preparation_evidence_sha256,
)
from database.database import PostgresDB
from database.operator_automation import (
    AUTOMATION_SPOT_DOCUMENTED_MARKET_FRESHNESS_GOAL_KEY,
    AUTOMATION_SPOT_NEAR_MARKET_V4_GOAL_KEY,
    AUTOMATION_SPOT_NEAR_MARKET_V5_GOAL_KEY,
    AUTOMATION_SPOT_NEAR_MARKET_V6_GOAL_KEY,
    AUTOMATION_SPOT_MINIMUM_SIZE_V7_GOAL_KEY,
    AUTOMATION_SPOT_MINIMUM_SIZE_V8_GOAL_KEY,
    AUTOMATION_SPOT_MINIMUM_SIZE_V9_GOAL_KEY,
    AUTOMATION_SPOT_PREVIEW_GATED_GOAL_KEY,
    AutomationDefinitionCreateCommand,
    AutomationMutationCommand,
    AutomationSpotSingleChildPlanTerms,
    AutomationSpotNearMarketMaterializationEvidence,
    AutomationSpotMinimumSizeMaterializationEvidence,
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


def _eligibility_evidence(seed: str, outcome: str) -> dict[str, str | None]:
    normalized = outcome.upper()
    if normalized == "UNKNOWN":
        return {
            "observed_at": None,
            "fresh_until": None,
            "evidence_sha256": None,
        }
    observed_at = datetime.now(timezone.utc)
    return {
        "observed_at": observed_at.isoformat(),
        "fresh_until": (
            (observed_at + timedelta(minutes=5)).isoformat()
            if normalized == "SUCCEEDED"
            else None
        ),
        "evidence_sha256": (
            hashlib.sha256(seed.encode("utf-8")).hexdigest()
            if normalized == "SUCCEEDED"
            else None
        ),
    }


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
        "automation_spot_eligibility_cycle",
        "automation_spot_eligibility_attempt",
        "automation_spot_live_proof_goal",
        "automation_spot_minimum_size_preparation",
        "automation_spot_near_market_preparation",
        "automation_spot_plan_goal",
        "automation_spot_preview_gated_goal",
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


def test_source_gated_spot_run_resume_is_exact_plan_bound_and_audited_without_calls(
    repository_harness: _Harness,
):
    repository = repository_harness.repository()
    _, plan, run = _prepare_spot_run(repository, "spot-source-gate-resume")
    repository.transition_run(
        run.run_id,
        OperatorAutomationRunState.BLOCKED,
        diagnostic_code="automation_active_order_catalog_read_not_authorized",
        command=_mutation("spot-source-gate-resume-initial-block"),
    )
    before = repository.list_run_events(run.run_id, limit=20, offset=0)
    command = _mutation("spot-source-gate-resume-command")

    first = repository.resume_spot_source_gated_run(
        run.run_id,
        expected_plan_sha256=plan.plan_sha256,
        command=command,
    )

    assert first.replayed is False
    assert first.entity.run.state is OperatorAutomationRunState.PREPARING
    assert first.entity.run.diagnostic_code == "automation_spot_source_gate_resumed"
    assert first.entity.run.live_attempt_consumed is False
    assert first.entity.run.coinbase_api_call_count == 0
    assert first.entity.run.create_call_count == 0
    assert first.entity.run.cancel_call_count == 0
    assert first.entity.cycle.state == "OPEN"
    assert repository.get_run(run.run_id) == first.entity.run

    with pytest.raises(AutomationStoreConflict) as in_progress:
        repository.resume_spot_source_gated_run(
            run.run_id,
            expected_plan_sha256=plan.plan_sha256,
            command=command,
        )
    assert in_progress.value.code == (
        "automation_spot_eligibility_cycle_in_progress"
    )

    events = repository.list_run_events(run.run_id, limit=20, offset=0)
    assert events.total == before.total + 1
    resume_event = events.items[-1]
    assert resume_event.from_state is OperatorAutomationRunState.BLOCKED
    assert resume_event.to_state is OperatorAutomationRunState.PREPARING
    assert resume_event.diagnostic_code == "automation_spot_source_gate_resumed"
    assert resume_event.idempotency_key_sha256 == hashlib.sha256(
        command.idempotency_key.encode("utf-8")
    ).hexdigest()
    assert resume_event.correlation_id == command.correlation_id

    category = AUTOMATION_SPOT_ELIGIBILITY_CATEGORIES[0]
    repository.start_spot_eligibility_attempt(
        run.run_id,
        category=category,
        command=_mutation("spot-source-gate-replay-start"),
    )
    repository.finalize_spot_eligibility_attempt(
        run.run_id,
        category=category,
        outcome="REJECTED",
        eligible=False,
        coinbase_api_call_count=0,
        call_count_exact=True,
        portfolio_id_sha256=None,
        **_eligibility_evidence("spot-source-gate-replay", "REJECTED"),
        command=_mutation("spot-source-gate-replay-finish"),
    )
    events_after_terminal = repository.list_run_events(
        run.run_id,
        limit=20,
        offset=0,
    )
    replay = repository.resume_spot_source_gated_run(
        run.run_id,
        expected_plan_sha256=plan.plan_sha256,
        command=command,
    )
    assert replay.replayed is True
    assert replay.audit_id == first.audit_id
    assert replay.entity.run.state is OperatorAutomationRunState.BLOCKED
    assert replay.entity.cycle.cycle_number == first.entity.cycle.cycle_number
    assert replay.entity.cycle.state == "REJECTED"
    assert repository.list_run_events(
        run.run_id,
        limit=20,
        offset=0,
    ).total == events_after_terminal.total

    for changed_command in (
        replace(command, payload_sha256="f" * 64),
        replace(command, actor_id="different-private-actor"),
        replace(command, correlation_id="different-correlation"),
        replace(command, operator_intent="different operator intent"),
    ):
        with pytest.raises(AutomationStoreConflict) as changed_replay:
            repository.resume_spot_source_gated_run(
                run.run_id,
                expected_plan_sha256=plan.plan_sha256,
                command=changed_command,
            )
        assert changed_replay.value.code == "automation_idempotency_conflict"

    assert repository.list_run_events(
        run.run_id,
        limit=20,
        offset=0,
    ).total == events_after_terminal.total


def test_source_gated_spot_run_resume_rejects_wrong_plan_or_block_reason(
    repository_harness: _Harness,
):
    repository = repository_harness.repository()
    _, plan, run = _prepare_spot_run(
        repository,
        "spot-source-gate-resume-rejection",
    )
    repository.transition_run(
        run.run_id,
        OperatorAutomationRunState.BLOCKED,
        diagnostic_code="automation_run_blocked",
        command=_mutation("spot-source-gate-resume-other-block"),
    )
    before = repository.list_run_events(run.run_id, limit=20, offset=0)

    with pytest.raises(AutomationStoreConflict) as wrong_plan:
        repository.resume_spot_source_gated_run(
            run.run_id,
            expected_plan_sha256="f" * 64,
            command=_mutation("spot-source-gate-resume-wrong-plan"),
        )
    assert wrong_plan.value.code == "automation_single_child_plan_mismatch"

    with pytest.raises(AutomationStoreConflict) as wrong_reason:
        repository.resume_spot_source_gated_run(
            run.run_id,
            expected_plan_sha256=plan.plan_sha256,
            command=_mutation("spot-source-gate-resume-wrong-reason"),
        )
    assert wrong_reason.value.code == "automation_single_child_run_not_resumable"
    current = repository.get_run(run.run_id)
    assert current is not None
    assert current.state is OperatorAutomationRunState.BLOCKED
    assert current.diagnostic_code == "automation_run_blocked"
    assert repository.list_run_events(
        run.run_id,
        limit=20,
        offset=0,
    ).total == before.total


def test_final_spot_authorization_cycle_is_distinct_and_starts_from_awaiting(
    repository_harness: _Harness,
):
    repository = repository_harness.repository()
    _, plan, run = _prepare_spot_run(repository, "spot-final-admission-cycle")
    _complete_eligible_cycle(
        repository,
        run.run_id,
        "spot-final-admission-cycle-source",
    )
    before = repository.list_run_events(run.run_id, limit=100, offset=0)

    with pytest.raises(AutomationStoreConflict) as source_refresh:
        repository.resume_spot_source_gated_run(
            run.run_id,
            expected_plan_sha256=plan.plan_sha256,
            command=_mutation("spot-final-admission-wrong-purpose"),
        )
    assert source_refresh.value.code == "automation_single_child_run_not_resumable"

    command = _mutation("spot-final-admission-cycle-allocate")
    allocation = repository.allocate_spot_authorization_cycle(
        run.run_id,
        expected_plan_sha256=plan.plan_sha256,
        command=command,
    )

    assert allocation.replayed is False
    assert allocation.entity.cycle.cycle_number == 2
    assert allocation.entity.cycle.state == "OPEN"
    assert allocation.entity.run.state is OperatorAutomationRunState.PREPARING
    assert allocation.entity.run.diagnostic_code == (
        "automation_spot_final_admission_started"
    )
    events = repository.list_run_events(run.run_id, limit=100, offset=0)
    assert events.total == before.total + 1
    event = events.items[-1]
    assert event.from_state is (
        OperatorAutomationRunState.AWAITING_OPERATOR_AUTHORIZATION
    )
    assert event.to_state is OperatorAutomationRunState.PREPARING
    assert event.diagnostic_code == "automation_spot_final_admission_started"
    assert event.idempotency_key_sha256 == hashlib.sha256(
        command.idempotency_key.encode("utf-8")
    ).hexdigest()


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


def _near_market_materialization_evidence(
    terms: AutomationSpotSingleChildPlanTerms,
    *,
    cycle_number: int,
    goal_key: str,
) -> AutomationSpotNearMarketMaterializationEvidence:
    diagnostic_code = "automation_near_market_terms_derived"
    categories = tuple(AUTOMATION_SPOT_ELIGIBILITY_CATEGORIES[:6])
    evidence_hash = near_market_preparation_evidence_sha256(
        call_count=6,
        categories=categories,
        diagnostic_code=diagnostic_code,
        outcome="MATERIALIZED",
        policy_revision=NEAR_MARKET_POLICY_REVISION,
        plan={
            "base_size": terms.base_size,
            "limit_price": terms.limit_price,
            "max_possible_execution_notional_usdc": (
                terms.max_possible_execution_notional_usdc
            ),
            "max_submitted_notional_usdc": terms.max_submitted_notional_usdc,
            "possible_execution_notional_usdc": (
                terms.possible_execution_notional_usdc
            ),
            "post_only": terms.post_only,
            "portfolio_id_sha256": terms.portfolio_id_sha256,
            "product_id": terms.product_id,
            "side": terms.side,
            "submitted_notional_usdc": terms.submitted_notional_usdc,
        },
    )
    return AutomationSpotNearMarketMaterializationEvidence(
        cycle_number=cycle_number,
        goal_key=goal_key,
        diagnostic_code=diagnostic_code,
        completed_categories=categories,
        coinbase_api_call_count=6,
        evidence_sha256=evidence_hash,
    )


def _minimum_size_materialization_evidence(
    terms: AutomationSpotSingleChildPlanTerms,
    *,
    cycle_number: int,
    goal_key: str,
    diagnostic_code: str = "minimum_size_v4_fee_reserve_conflict",
) -> AutomationSpotMinimumSizeMaterializationEvidence:
    categories = tuple(AUTOMATION_SPOT_ELIGIBILITY_CATEGORIES[:6])
    evidence_hash = minimum_size_preparation_evidence_sha256(
        call_count=6,
        categories=categories,
        diagnostic_code=diagnostic_code,
        outcome="MATERIALIZED",
        policy_revision=MINIMUM_SIZE_POLICY_REVISION,
        plan={
            "base_size": terms.base_size,
            "limit_price": terms.limit_price,
            "max_possible_execution_notional_usdc": (
                terms.max_possible_execution_notional_usdc
            ),
            "max_submitted_notional_usdc": terms.max_submitted_notional_usdc,
            "possible_execution_notional_usdc": (
                terms.possible_execution_notional_usdc
            ),
            "post_only": terms.post_only,
            "portfolio_id_sha256": terms.portfolio_id_sha256,
            "product_id": terms.product_id,
            "side": terms.side,
            "submitted_notional_usdc": terms.submitted_notional_usdc,
            "v4_boundary_classification": diagnostic_code,
        },
    )
    return AutomationSpotMinimumSizeMaterializationEvidence(
        cycle_number=cycle_number,
        goal_key=goal_key,
        diagnostic_code=diagnostic_code,
        completed_categories=categories,
        coinbase_api_call_count=6,
        evidence_sha256=evidence_hash,
    )


def _materialize_near_market_candidate(
    repository: OperatorAutomationRepository,
    seed: str,
):
    claimed = repository.start_spot_near_market_preparation(
        _mutation(f"{seed}-preparation")
    ).entity
    terms = _spot_plan_terms(
        base_size="0.00001",
        limit_price="49999",
        submitted_notional_usdc="0.49999",
        possible_execution_notional_usdc="0.49999",
        post_only=True,
    )
    created = repository.create_definition(
        _definition_command(
            f"{seed}-definition",
            product_ids=("BTC-USDC",),
        ),
        spot_single_child_plan=terms,
        spot_goal_key=claimed.goal_key,
        spot_near_market_materialization=_near_market_materialization_evidence(
            terms,
            cycle_number=claimed.cycle_number,
            goal_key=claimed.goal_key,
        ),
    ).entity
    enabled = repository.transition_definition(
        created.definition_id,
        "enable",
        _mutation(f"{seed}-enable"),
    ).entity
    run = repository.claim_one_shot_run(
        enabled.definition_id,
        _mutation(f"{seed}-run"),
    ).entity
    run = repository.transition_run(
        run.run_id,
        OperatorAutomationRunState.PREPARING,
        diagnostic_code="preparing",
        command=_mutation(f"{seed}-preparing"),
    ).entity
    return claimed, created, run


def _seal_minimum_size_predecessor(
    repository: OperatorAutomationRepository,
    seed: str,
) -> None:
    _seal_rejected_v3_predecessor(repository, seed)
    claimed = repository.start_spot_near_market_preparation(
        _mutation(f"{seed}-v4-preparation")
    ).entity
    categories = tuple(AUTOMATION_SPOT_ELIGIBILITY_CATEGORIES[:6])
    diagnostic_code = "near_market_no_valid_size"
    evidence = near_market_preparation_evidence_sha256(
        call_count=6,
        categories=categories,
        diagnostic_code=diagnostic_code,
        outcome="BLOCKED",
        policy_revision=NEAR_MARKET_POLICY_REVISION,
        plan=None,
    )
    repository.finalize_spot_near_market_preparation(
        cycle_number=claimed.cycle_number,
        goal_key=claimed.goal_key,
        state="BLOCKED",
        diagnostic_code=diagnostic_code,
        completed_categories=categories,
        coinbase_api_call_count=6,
        call_count_exact=True,
        evidence_sha256=evidence,
        definition_id=None,
    )


def _materialize_minimum_size_candidate(
    repository: OperatorAutomationRepository,
    seed: str,
):
    claimed = repository.start_spot_minimum_size_preparation(
        _mutation(f"{seed}-preparation")
    ).entity
    terms = _spot_plan_terms(
        base_size="0.00001",
        limit_price="100000",
        submitted_notional_usdc="1",
        possible_execution_notional_usdc="1",
        max_possible_execution_notional_usdc="1.01",
        post_only=True,
    )
    created = repository.create_definition(
        _definition_command(
            f"{seed}-definition",
            product_ids=("BTC-USDC",),
        ),
        spot_single_child_plan=terms,
        spot_goal_key=claimed.goal_key,
        spot_minimum_size_materialization=_minimum_size_materialization_evidence(
            terms,
            cycle_number=claimed.cycle_number,
            goal_key=claimed.goal_key,
        ),
    ).entity
    enabled = repository.transition_definition(
        created.definition_id,
        "enable",
        _mutation(f"{seed}-enable"),
    ).entity
    run = repository.claim_one_shot_run(
        enabled.definition_id,
        _mutation(f"{seed}-run"),
    ).entity
    run = repository.transition_run(
        run.run_id,
        OperatorAutomationRunState.PREPARING,
        diagnostic_code="preparing",
        command=_mutation(f"{seed}-preparing"),
    ).entity
    return claimed, created, run


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


def _allocate_spot_eligibility_cycle(
    repository: OperatorAutomationRepository,
    run_id: str,
    plan_sha256: str,
    seed: str,
):
    run = repository.get_run(run_id)
    assert run is not None
    if run.state is OperatorAutomationRunState.PREPARING:
        run = repository.transition_run(
            run_id,
            OperatorAutomationRunState.BLOCKED,
            diagnostic_code="automation_active_order_catalog_read_not_authorized",
            command=_mutation(f"{seed}-source-gate"),
        ).entity
    assert run.state is OperatorAutomationRunState.BLOCKED
    assert run.diagnostic_code in {
        "automation_active_order_catalog_read_not_authorized",
        "automation_spot_eligibility_refresh_required",
    }
    resumed = repository.resume_spot_source_gated_run(
        run_id,
        expected_plan_sha256=plan_sha256,
        command=_mutation(f"{seed}-cycle"),
    )
    goal_key = repository.get_spot_goal_key_for_run(run_id)
    cycles = repository.list_spot_eligibility_cycles(goal_key=goal_key)
    assert cycles[-1].state == "OPEN"
    assert resumed.entity.run.state is OperatorAutomationRunState.PREPARING
    assert resumed.entity.cycle == cycles[-1]
    return resumed, resumed.entity.cycle


def _complete_eligible_cycle(
    repository: OperatorAutomationRepository,
    run_id: str,
    seed: str,
) -> None:
    run = repository.get_run(run_id)
    assert run is not None and run.definition_revision is not None
    plan = repository.get_spot_single_child_plan(
        run.definition_id,
        run.definition_revision,
    )
    assert plan is not None
    goal_key = repository.get_spot_goal_key_for_run(run_id)
    cycles = repository.list_spot_eligibility_cycles(goal_key=goal_key)
    if not cycles or cycles[-1].state != "OPEN":
        _allocate_spot_eligibility_cycle(
            repository,
            run_id,
            plan.plan_sha256,
            seed,
        )
        cycles = repository.list_spot_eligibility_cycles(goal_key=goal_key)
    cycle_number = cycles[-1].cycle_number
    for index, category in enumerate(AUTOMATION_SPOT_ELIGIBILITY_CATEGORIES):
        started = repository.start_spot_eligibility_attempt(
            run_id,
            category=category,
            command=_mutation(f"{seed}-{index}-start"),
        )
        assert started.entity.outcome is None
        assert started.entity.allowance_consumed is True
        finalized = repository.finalize_spot_eligibility_attempt(
            run_id,
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
            **_eligibility_evidence(f"{seed}-{index}", "SUCCEEDED"),
            command=_mutation(f"{seed}-{index}-finish"),
        )
        assert finalized.entity.outcome == "SUCCEEDED"
        assert finalized.entity.eligible is True
        assert finalized.entity.cycle_number == cycle_number
    cycle = repository.list_spot_eligibility_cycles(goal_key=goal_key)[-1]
    assert cycle.state == "SUCCEEDED"
    assert cycle.coinbase_api_call_count == len(
        AUTOMATION_SPOT_ELIGIBILITY_CATEGORIES
    )
    assert cycle.call_count_exact is True
    assert cycle.fresh_until is not None
    current = repository.get_run(run_id)
    assert current is not None
    assert current.state is OperatorAutomationRunState.AWAITING_OPERATOR_AUTHORIZATION
    assert current.diagnostic_code == "awaiting_operator_authorization"


def _reject_v3_cycle_for_missing_market_observation(
    repository: OperatorAutomationRepository,
    run_id: str,
    seed: str,
) -> None:
    run = repository.get_run(run_id)
    assert run is not None and run.definition_revision is not None
    plan = repository.get_spot_single_child_plan(
        run.definition_id,
        run.definition_revision,
    )
    assert plan is not None
    _, cycle = _allocate_spot_eligibility_cycle(
        repository,
        run_id,
        plan.plan_sha256,
        seed,
    )
    for index, category in enumerate(AUTOMATION_SPOT_ELIGIBILITY_CATEGORIES):
        repository.start_spot_eligibility_attempt(
            run_id,
            category=category,
            command=_mutation(f"{seed}-{index}-start"),
        )
        if category == "BEST_BID_ASK":
            rejected = repository.finalize_spot_eligibility_attempt(
                run_id,
                category=category,
                outcome="REJECTED",
                eligible=False,
                coinbase_api_call_count=1,
                call_count_exact=True,
                portfolio_id_sha256=None,
                observed_at=None,
                fresh_until=None,
                evidence_sha256=None,
                command=_mutation(f"{seed}-{index}-finish"),
            ).entity
            assert rejected.observed_at is None
            assert rejected.fresh_until is None
            assert rejected.evidence_sha256 is None
            break
        repository.finalize_spot_eligibility_attempt(
            run_id,
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
            **_eligibility_evidence(f"{seed}-{index}", "SUCCEEDED"),
            command=_mutation(f"{seed}-{index}-finish"),
        )
    persisted = repository.list_spot_eligibility_cycles(
        goal_key=AUTOMATION_SPOT_DOCUMENTED_MARKET_FRESHNESS_GOAL_KEY,
    )[-1]
    assert persisted.cycle_number == cycle.cycle_number
    assert persisted.state == "REJECTED"
    assert persisted.call_count_exact is True
    assert persisted.fresh_until is None


def _await_spot_authorization(
    repository: OperatorAutomationRepository,
    run_id: str,
    seed: str,
):
    current = repository.get_run(run_id)
    assert current is not None
    if current.state is OperatorAutomationRunState.AWAITING_OPERATOR_AUTHORIZATION:
        return current
    if current.state is OperatorAutomationRunState.BLOCKED:
        # Historical Create-ledger tests predate the source-gated eligibility
        # ledger. The production repository deliberately has no
        # BLOCKED -> AWAITING transition because the separately required
        # canonical active-order catalog is outside this repository phase.
        repository.database.execute_update(
            f'UPDATE "{repository.schema}".automation_run '
            "SET state = 'PREPARING', diagnostic_code = 'test_fixture_preparing' "
            "WHERE run_id = %s",
            (run_id,),
        )
    return repository.transition_run(
        run_id,
        OperatorAutomationRunState.AWAITING_OPERATOR_AUTHORIZATION,
        diagnostic_code="awaiting_operator_authorization",
        command=_mutation(f"{seed}-awaiting"),
    ).entity


def test_spot_eligibility_v2_adds_final_account_catalog_and_preserves_v1_rows(
    repository_harness: _Harness,
):
    repository = repository_harness.repository()
    _, plan, run = _prepare_spot_run(repository, "eligibility-policy-revision")
    _, cycle = _allocate_spot_eligibility_cycle(
        repository,
        run.run_id,
        plan.plan_sha256,
        "eligibility-policy-revision",
    )
    assert cycle.policy_revision == 2
    assert AUTOMATION_SPOT_ELIGIBILITY_CATEGORIES[-1] == (
        "ACCOUNT_ACTIVE_SPOT_ORDER_CATALOG"
    )

    repository_harness.database.execute_update(
        f'ALTER TABLE "{repository_harness.schema}".automation_spot_eligibility_cycle '
        "DISABLE TRIGGER automation_spot_cycle_binding_no_update"
    )
    repository_harness.database.execute_update(
        f'UPDATE "{repository_harness.schema}".automation_spot_eligibility_cycle '
        "SET policy_revision = 1 WHERE goal_key = %s AND cycle_number = %s",
        (cycle.goal_key, cycle.cycle_number),
    )
    repository_harness.database.execute_update(
        f'ALTER TABLE "{repository_harness.schema}".automation_spot_eligibility_cycle '
        "ENABLE TRIGGER automation_spot_cycle_binding_no_update"
    )
    repository.ensure_schema()
    preserved = repository.list_spot_eligibility_cycles()[0]
    assert preserved.policy_revision == 1


def test_spot_create_requires_fresh_v2_eight_category_cycle(
    repository_harness: _Harness,
):
    repository = repository_harness.repository()
    _, plan, run = _prepare_spot_run(repository, "spot-create-policy-revision")
    _complete_eligible_cycle(repository, run.run_id, "spot-create-policy-revision")
    cycle = repository.list_spot_eligibility_cycles()[-1]
    assert cycle.policy_revision == 2

    repository_harness.database.execute_update(
        f'ALTER TABLE "{repository_harness.schema}".automation_spot_eligibility_cycle '
        "DISABLE TRIGGER automation_spot_cycle_binding_no_update"
    )
    repository_harness.database.execute_update(
        f'UPDATE "{repository_harness.schema}".automation_spot_eligibility_cycle '
        "SET policy_revision = 1 WHERE goal_key = %s AND cycle_number = %s",
        (cycle.goal_key, cycle.cycle_number),
    )
    repository_harness.database.execute_update(
        f'ALTER TABLE "{repository_harness.schema}".automation_spot_eligibility_cycle '
        "ENABLE TRIGGER automation_spot_cycle_binding_no_update"
    )
    with pytest.raises(AutomationStoreConflict) as blocked:
        repository.start_spot_create_invocation(
            run.run_id,
            eligibility_cycle=cycle.cycle_number,
            command=_mutation("spot-create-policy-revision-start"),
        )
    assert blocked.value.code == "automation_spot_exact_eligibility_not_proven"


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


def test_spot_eligibility_cycle_is_goal_global_bound_and_atomically_resumed(
    repository_harness: _Harness,
):
    repository = repository_harness.repository()
    definition, plan, run = _prepare_spot_run(repository, "spot-eligibility")
    goal_before = repository.get_spot_live_proof_goal()
    events_before = repository.list_run_events(run.run_id, limit=50, offset=0)
    blocked = repository.transition_run(
        run.run_id,
        OperatorAutomationRunState.BLOCKED,
        diagnostic_code="automation_active_order_catalog_read_not_authorized",
        command=_mutation("spot-eligibility-source-gate"),
    ).entity
    command = _mutation("spot-eligibility-cycle")

    resumed = repository.resume_spot_source_gated_run(
        run.run_id,
        expected_plan_sha256=plan.plan_sha256,
        command=command,
    )
    with pytest.raises(AutomationStoreConflict) as replay_in_progress:
        repository.resume_spot_source_gated_run(
            run.run_id,
            expected_plan_sha256=plan.plan_sha256,
            command=command,
        )

    assert resumed.entity.run.state is OperatorAutomationRunState.PREPARING
    assert replay_in_progress.value.code == (
        "automation_spot_eligibility_cycle_in_progress"
    )
    cycles = repository.list_spot_eligibility_cycles()
    assert len(cycles) == 1
    cycle = cycles[0]
    assert resumed.entity.cycle == cycle
    assert cycle.goal_key == (
        "operator_spot_automation_single_child_execution_adapter_v1"
    )
    assert cycle.cycle_number == 1
    assert cycle.state == "OPEN"
    assert cycle.run_id == run.run_id
    assert cycle.definition_id == definition.definition_id
    assert cycle.definition_revision == definition.revision
    assert cycle.plan_sha256 == plan.plan_sha256
    assert cycle.portfolio_id_sha256 == plan.portfolio_id_sha256
    assert cycle.product_id == "BTC-USDC"
    assert cycle.client_order_id == repository.deterministic_spot_client_order_id(
        run_id=run.run_id,
        plan_sha256=plan.plan_sha256,
    )
    assert cycle.coinbase_api_call_count is None
    assert cycle.call_count_exact is False
    assert cycle.fresh_until is None
    assert repository.get_spot_live_proof_goal() == goal_before
    assert repository.get_spot_run_execution(run.run_id) is None
    assert repository.list_run_events(
        run.run_id,
        limit=50,
        offset=0,
    ).total == events_before.total + 2

    with pytest.raises(psycopg2.errors.RaiseException):
        repository_harness.database.execute_update(
            f'UPDATE "{repository_harness.schema}".automation_spot_eligibility_cycle '
            "SET product_id = 'ETH-USDC' WHERE goal_key = %s AND cycle_number = 1",
            (cycle.goal_key,),
        )
    with pytest.raises(psycopg2.errors.RaiseException):
        repository_harness.database.execute_update(
            f'DELETE FROM "{repository_harness.schema}".automation_spot_eligibility_cycle '
            "WHERE goal_key = %s AND cycle_number = 1",
            (cycle.goal_key,),
        )

    assert blocked.live_attempt_consumed is False


def test_spot_eligibility_mutations_lock_idempotency_before_goal_singleton(
    repository_harness: _Harness,
    monkeypatch: pytest.MonkeyPatch,
):
    repository = repository_harness.repository()
    _definition, plan, run = _prepare_spot_run(
        repository,
        "spot-eligibility-lock-order",
    )
    repository.transition_run(
        run.run_id,
        OperatorAutomationRunState.BLOCKED,
        diagnostic_code="automation_active_order_catalog_read_not_authorized",
        command=_mutation("spot-eligibility-lock-order-source-gate"),
    )
    events: list[str] = []
    original_idempotency = repository._idempotency_replay
    original_goal = repository._lock_spot_live_goal_cursor

    def traced_idempotency(*args, **kwargs):
        events.append("idempotency")
        return original_idempotency(*args, **kwargs)

    def traced_goal(*args, **kwargs):
        events.append("goal")
        return original_goal(*args, **kwargs)

    monkeypatch.setattr(repository, "_idempotency_replay", traced_idempotency)
    monkeypatch.setattr(repository, "_lock_spot_live_goal_cursor", traced_goal)

    repository.resume_spot_source_gated_run(
        run.run_id,
        expected_plan_sha256=plan.plan_sha256,
        command=_mutation("spot-eligibility-lock-order-resume"),
    )
    assert events == ["idempotency", "goal"]

    events.clear()
    category = AUTOMATION_SPOT_ELIGIBILITY_CATEGORIES[0]
    repository.start_spot_eligibility_attempt(
        run.run_id,
        category=category,
        command=_mutation("spot-eligibility-lock-order-start"),
    )
    assert events == ["idempotency", "goal"]

    events.clear()
    repository.finalize_spot_eligibility_attempt(
        run.run_id,
        category=category,
        outcome="REJECTED",
        eligible=False,
        coinbase_api_call_count=0,
        call_count_exact=True,
        portfolio_id_sha256=None,
        **_eligibility_evidence(
            "spot-eligibility-lock-order-finalize",
            "REJECTED",
        ),
        command=_mutation("spot-eligibility-lock-order-finalize"),
    )
    assert events == ["idempotency", "goal"]


def test_spot_eligibility_attempts_use_open_cycle_and_fixed_category_order(
    repository_harness: _Harness,
):
    repository = repository_harness.repository()
    _, plan, run = _prepare_spot_run(repository, "spot-attempt-order")
    _, cycle = _allocate_spot_eligibility_cycle(
        repository,
        run.run_id,
        plan.plan_sha256,
        "spot-attempt-order",
    )
    category = AUTOMATION_SPOT_ELIGIBILITY_CATEGORIES[0]
    command = _mutation("spot-attempt-order-start")

    started = repository.start_spot_eligibility_attempt(
        run.run_id,
        category=category,
        command=command,
    )
    replay = repository.start_spot_eligibility_attempt(
        run.run_id,
        category=category,
        command=command,
    )
    assert started.entity.cycle_number == cycle.cycle_number
    assert replay.replayed is True
    assert replay.entity == started.entity
    with pytest.raises(AutomationStoreConflict) as duplicate:
        repository.start_spot_eligibility_attempt(
            run.run_id,
            category=category,
            command=_mutation("spot-attempt-order-duplicate"),
        )
    assert duplicate.value.code == "automation_spot_eligibility_category_consumed"

    with pytest.raises(TypeError):
        repository.start_spot_eligibility_attempt(
            run.run_id,
            cycle_number=cycle.cycle_number,
            category=category,
            command=_mutation("caller-cycle-forbidden"),
        )
    with pytest.raises(AutomationStoreConflict) as open_attempt:
        repository.start_spot_eligibility_attempt(
            run.run_id,
            category=AUTOMATION_SPOT_ELIGIBILITY_CATEGORIES[1],
            command=_mutation("spot-attempt-order-open-attempt"),
        )
    assert open_attempt.value.code == (
        "automation_spot_eligibility_attempt_in_progress"
    )

    finalized = repository.finalize_spot_eligibility_attempt(
        run.run_id,
        category=category,
        outcome="SUCCEEDED",
        eligible=True,
        coinbase_api_call_count=1,
        call_count_exact=True,
        portfolio_id_sha256=None,
        **_eligibility_evidence("spot-attempt-order", "SUCCEEDED"),
        command=_mutation("spot-attempt-order-finish"),
    ).entity
    assert finalized.outcome == "SUCCEEDED"
    assert finalized.coinbase_api_call_count == 1
    assert finalized.call_count_exact is True
    assert finalized.observed_at is not None
    assert finalized.fresh_until is not None
    assert finalized.evidence_sha256 is not None

    with pytest.raises(AutomationStoreConflict) as skipped:
        repository.start_spot_eligibility_attempt(
            run.run_id,
            category=AUTOMATION_SPOT_ELIGIBILITY_CATEGORIES[2],
            command=_mutation("spot-attempt-order-skipped"),
        )
    assert skipped.value.code == (
        "automation_spot_eligibility_category_sequence_invalid"
    )
    with pytest.raises(AutomationStoreInvalid) as category_invalid:
        repository.start_spot_eligibility_attempt(
            run.run_id,
            category="UNAPPROVED_READ",
            command=_mutation("spot-attempt-order-category-invalid"),
        )
    assert category_invalid.value.code == "automation_spot_eligibility_category_invalid"


@pytest.mark.parametrize(
    (
        "outcome",
        "eligible",
        "call_count",
        "call_count_exact",
        "expected_cycle_state",
    ),
    [
        ("SUCCEEDED", True, 3, True, "OPEN"),
        ("REJECTED", False, 0, True, "REJECTED"),
        ("REJECTED", False, 4, True, "REJECTED"),
        ("UNKNOWN", False, None, False, "UNKNOWN"),
    ],
)
def test_spot_eligibility_result_shapes_allow_zero_rejections_and_multipage_counts(
    repository_harness: _Harness,
    outcome: str,
    eligible: bool,
    call_count: int | None,
    call_count_exact: bool,
    expected_cycle_state: str,
):
    repository = repository_harness.repository()
    _, plan, run = _prepare_spot_run(
        repository,
        f"eligibility-shape-{outcome.lower()}-{call_count}",
    )
    _allocate_spot_eligibility_cycle(
        repository,
        run.run_id,
        plan.plan_sha256,
        f"eligibility-shape-{outcome.lower()}-{call_count}",
    )
    category = AUTOMATION_SPOT_ELIGIBILITY_CATEGORIES[0]
    repository.start_spot_eligibility_attempt(
        run.run_id,
        category=category,
        command=_mutation(f"shape-{outcome}-{call_count}-start"),
    )

    result = repository.finalize_spot_eligibility_attempt(
        run.run_id,
        category=category,
        outcome=outcome,
        eligible=eligible,
        coinbase_api_call_count=call_count,
        call_count_exact=call_count_exact,
        portfolio_id_sha256=None,
        **_eligibility_evidence(
            f"shape-{outcome}-{call_count}",
            outcome,
        ),
        command=_mutation(f"shape-{outcome}-{call_count}-finish"),
    )

    assert result.entity.outcome == outcome
    assert result.entity.coinbase_api_call_count == call_count
    cycle = repository.list_spot_eligibility_cycles()[-1]
    assert cycle.state == expected_cycle_state
    if expected_cycle_state == "OPEN":
        assert cycle.coinbase_api_call_count is None
        assert repository.get_run(run.run_id).state is (
            OperatorAutomationRunState.PREPARING
        )
    else:
        assert cycle.coinbase_api_call_count == call_count
        current = repository.get_run(run.run_id)
        assert current is not None
        assert current.state is OperatorAutomationRunState.BLOCKED
        assert current.diagnostic_code == (
            "automation_spot_eligibility_refresh_required"
        )


@pytest.mark.parametrize(
    ("outcome", "eligible", "call_count", "call_count_exact"),
    [
        ("SUCCEEDED", True, 0, True),
        ("SUCCEEDED", False, 1, True),
        ("SUCCEEDED", True, None, False),
        ("REJECTED", True, 1, True),
        ("REJECTED", False, None, False),
        ("UNKNOWN", True, None, False),
        ("UNKNOWN", False, 1, True),
    ],
)
def test_spot_eligibility_result_shapes_reject_incoherent_evidence(
    repository_harness: _Harness,
    outcome: str,
    eligible: bool,
    call_count: int | None,
    call_count_exact: bool,
):
    repository = repository_harness.repository()
    _, plan, run = _prepare_spot_run(
        repository,
        f"eligibility-invalid-{outcome.lower()}-{eligible}-{call_count}",
    )
    _allocate_spot_eligibility_cycle(
        repository,
        run.run_id,
        plan.plan_sha256,
        f"eligibility-invalid-{outcome.lower()}-{eligible}-{call_count}",
    )
    category = AUTOMATION_SPOT_ELIGIBILITY_CATEGORIES[0]
    repository.start_spot_eligibility_attempt(
        run.run_id,
        category=category,
        command=_mutation(
            f"invalid-{outcome}-{eligible}-{call_count}-start"
        ),
    )

    with pytest.raises(AutomationStoreInvalid) as invalid:
        repository.finalize_spot_eligibility_attempt(
            run.run_id,
            category=category,
            outcome=outcome,
            eligible=eligible,
            coinbase_api_call_count=call_count,
            call_count_exact=call_count_exact,
            portfolio_id_sha256=None,
            **_eligibility_evidence(
                f"invalid-{outcome}-{eligible}-{call_count}",
                outcome,
            ),
            command=_mutation(
                f"invalid-{outcome}-{eligible}-{call_count}-finish"
            ),
        )
    assert invalid.value.code == "automation_spot_eligibility_result_invalid"


def test_spot_eligibility_freshness_and_evidence_shapes_fail_closed(
    repository_harness: _Harness,
):
    repository = repository_harness.repository()
    _, plan, run = _prepare_spot_run(repository, "eligibility-freshness")
    _allocate_spot_eligibility_cycle(
        repository,
        run.run_id,
        plan.plan_sha256,
        "eligibility-freshness",
    )
    category = AUTOMATION_SPOT_ELIGIBILITY_CATEGORIES[0]
    repository.start_spot_eligibility_attempt(
        run.run_id,
        category=category,
        command=_mutation("eligibility-freshness-start"),
    )
    evidence = _eligibility_evidence("eligibility-freshness", "SUCCEEDED")
    invalid_shapes = (
        {**evidence, "observed_at": None},
        {**evidence, "fresh_until": None},
        {**evidence, "evidence_sha256": None},
        {**evidence, "fresh_until": evidence["observed_at"]},
        {**evidence, "evidence_sha256": "A" * 64},
    )
    for index, invalid_evidence in enumerate(invalid_shapes):
        with pytest.raises(AutomationStoreInvalid) as invalid:
            repository.finalize_spot_eligibility_attempt(
                run.run_id,
                category=category,
                outcome="SUCCEEDED",
                eligible=True,
                coinbase_api_call_count=1,
                call_count_exact=True,
                portfolio_id_sha256=None,
                **invalid_evidence,
                command=_mutation(f"eligibility-freshness-invalid-{index}"),
            )
        assert invalid.value.code == "automation_spot_eligibility_result_invalid"

    with pytest.raises(AutomationStoreInvalid) as rejected_without_observation:
        repository.finalize_spot_eligibility_attempt(
            run.run_id,
            category=category,
            outcome="REJECTED",
            eligible=False,
            coinbase_api_call_count=0,
            call_count_exact=True,
            portfolio_id_sha256=None,
            observed_at=None,
            fresh_until=None,
            evidence_sha256=None,
            command=_mutation("eligibility-rejected-no-observation"),
        )
    assert rejected_without_observation.value.code == (
        "automation_spot_eligibility_result_invalid"
    )

    with pytest.raises(AutomationStoreInvalid) as unknown_with_evidence:
        repository.finalize_spot_eligibility_attempt(
            run.run_id,
            category=category,
            outcome="UNKNOWN",
            eligible=False,
            coinbase_api_call_count=None,
            call_count_exact=False,
            portfolio_id_sha256=None,
            observed_at=evidence["observed_at"],
            fresh_until=None,
            evidence_sha256=None,
            command=_mutation("eligibility-unknown-with-observation"),
        )
    assert unknown_with_evidence.value.code == (
        "automation_spot_eligibility_result_invalid"
    )


def test_spot_eligibility_result_shape_is_database_enforced(
    repository_harness: _Harness,
):
    repository = repository_harness.repository()
    _, plan, run = _prepare_spot_run(repository, "eligibility-db-shape")
    _, cycle = _allocate_spot_eligibility_cycle(
        repository,
        run.run_id,
        plan.plan_sha256,
        "eligibility-db-shape",
    )
    category = AUTOMATION_SPOT_ELIGIBILITY_CATEGORIES[0]
    repository.start_spot_eligibility_attempt(
        run.run_id,
        category=category,
        command=_mutation("eligibility-db-shape-start"),
    )

    with pytest.raises(psycopg2.errors.CheckViolation):
        repository_harness.database.execute_update(
            f'UPDATE "{repository_harness.schema}".'
            "automation_spot_eligibility_attempt "
            "SET outcome = 'UNKNOWN', eligible = FALSE, "
            "coinbase_api_call_count = 1, call_count_exact = TRUE, "
            "finalized_at = NOW() "
            "WHERE run_id = %s AND cycle_number = %s AND category = %s",
            (run.run_id, cycle.cycle_number, category),
        )


def test_spot_eligibility_restart_terminalizes_open_cycle_and_allocates_next(
    repository_harness: _Harness,
):
    repository = repository_harness.repository()
    _, plan, run = _prepare_spot_run(repository, "eligibility-restart")
    _, first_cycle = _allocate_spot_eligibility_cycle(
        repository,
        run.run_id,
        plan.plan_sha256,
        "eligibility-restart",
    )
    category = AUTOMATION_SPOT_ELIGIBILITY_CATEGORIES[0]
    repository.start_spot_eligibility_attempt(
        run.run_id,
        category=category,
        command=_mutation("eligibility-restart-attempt"),
    )
    goal_before = repository.get_spot_live_proof_goal()

    restarted = repository_harness.repository()
    recovered = restarted.recover_runs_after_restart()

    assert [item.run_id for item in recovered] == [run.run_id]
    attempt = restarted.list_spot_eligibility_attempts(
        run.run_id,
        cycle_number=first_cycle.cycle_number,
    )[0]
    assert attempt.outcome == "UNKNOWN"
    assert attempt.eligible is False
    assert attempt.coinbase_api_call_count is None
    assert attempt.call_count_exact is False
    cycle = restarted.list_spot_eligibility_cycles()[0]
    assert cycle.state == "UNKNOWN"
    assert cycle.coinbase_api_call_count is None
    assert cycle.call_count_exact is False
    current = restarted.get_run(run.run_id)
    assert current is not None
    assert current.state is OperatorAutomationRunState.BLOCKED
    assert current.diagnostic_code == (
        "automation_active_order_catalog_read_not_authorized"
    )
    assert restarted.get_spot_live_proof_goal() == goal_before
    assert restarted.get_spot_run_execution(run.run_id) is None
    assert restarted.recover_runs_after_restart() == ()

    resumed = restarted.resume_spot_source_gated_run(
        run.run_id,
        expected_plan_sha256=plan.plan_sha256,
        command=_mutation("eligibility-restart-next-cycle"),
    )
    assert resumed.entity.run.state is OperatorAutomationRunState.PREPARING
    assert resumed.entity.cycle.cycle_number == 2
    cycles = restarted.list_spot_eligibility_cycles()
    assert [item.cycle_number for item in cycles] == [1, 2]
    assert [item.state for item in cycles] == ["UNKNOWN", "OPEN"]

    after_empty_cycle_restart = repository_harness.repository()
    recovered_empty = after_empty_cycle_restart.recover_runs_after_restart()
    assert [item.run_id for item in recovered_empty] == [run.run_id]
    assert [item.state for item in after_empty_cycle_restart.list_spot_eligibility_cycles()] == [
        "UNKNOWN",
        "UNKNOWN",
    ]


def test_spot_eligibility_cycle_allocation_rolls_back_resume_on_insert_failure(
    repository_harness: _Harness,
    monkeypatch: pytest.MonkeyPatch,
):
    repository = repository_harness.repository()
    _, plan, run = _prepare_spot_run(repository, "eligibility-atomic")
    blocked = repository.transition_run(
        run.run_id,
        OperatorAutomationRunState.BLOCKED,
        diagnostic_code="automation_active_order_catalog_read_not_authorized",
        command=_mutation("eligibility-atomic-source-gate"),
    ).entity
    event_count = repository.list_run_events(run.run_id, limit=50, offset=0).total
    idempotency_count = repository_harness.scalar(
        f'SELECT COUNT(*) FROM "{repository_harness.schema}".automation_idempotency'
    )

    def fail_cycle_insert(*_args, **_kwargs):
        raise RuntimeError("synthetic_cycle_insert_failure")

    monkeypatch.setattr(
        repository,
        "_insert_spot_eligibility_cycle_cursor",
        fail_cycle_insert,
    )
    with pytest.raises(RuntimeError, match="synthetic_cycle_insert_failure"):
        repository.resume_spot_source_gated_run(
            run.run_id,
            expected_plan_sha256=plan.plan_sha256,
            command=_mutation("eligibility-atomic-resume"),
        )

    assert repository.get_run(run.run_id) == blocked
    assert repository.list_spot_eligibility_cycles() == ()
    assert repository.list_run_events(run.run_id, limit=50, offset=0).total == (
        event_count
    )
    assert repository_harness.scalar(
        f'SELECT COUNT(*) FROM "{repository_harness.schema}".automation_idempotency'
    ) == idempotency_count


def test_spot_eligibility_goal_has_at_most_ten_terminal_cycles(
    repository_harness: _Harness,
):
    repository = repository_harness.repository()
    _, plan, run = _prepare_spot_run(repository, "eligibility-cycle-limit")

    for cycle_number in range(1, 11):
        _, cycle = _allocate_spot_eligibility_cycle(
            repository,
            run.run_id,
            plan.plan_sha256,
            f"eligibility-cycle-limit-{cycle_number}",
        )
        assert cycle.cycle_number == cycle_number
        category = AUTOMATION_SPOT_ELIGIBILITY_CATEGORIES[0]
        repository.start_spot_eligibility_attempt(
            run.run_id,
            category=category,
            command=_mutation(f"eligibility-limit-{cycle_number}-start"),
        )
        repository.finalize_spot_eligibility_attempt(
            run.run_id,
            category=category,
            outcome="REJECTED",
            eligible=False,
            coinbase_api_call_count=0,
            call_count_exact=True,
            portfolio_id_sha256=None,
            **_eligibility_evidence(
                f"eligibility-limit-{cycle_number}",
                "REJECTED",
            ),
            command=_mutation(f"eligibility-limit-{cycle_number}-finish"),
        )

    with pytest.raises(AutomationStoreConflict) as exhausted:
        repository.resume_spot_source_gated_run(
            run.run_id,
            expected_plan_sha256=plan.plan_sha256,
            command=_mutation("eligibility-cycle-limit-11"),
        )
    assert exhausted.value.code == "automation_spot_eligibility_cycles_exhausted"
    assert len(repository.list_spot_eligibility_cycles()) == 10
    assert repository.get_run(run.run_id).state is (
        OperatorAutomationRunState.BLOCKED
    )


def test_portfolio_catalog_proof_is_exactly_bound_to_the_run_plan(
    repository_harness: _Harness,
):
    repository = repository_harness.repository()
    _, plan, run = _prepare_spot_run(repository, "spot-catalog-binding")
    _allocate_spot_eligibility_cycle(
        repository,
        run.run_id,
        plan.plan_sha256,
        "spot-catalog-binding",
    )
    first_category = AUTOMATION_SPOT_ELIGIBILITY_CATEGORIES[0]
    repository.start_spot_eligibility_attempt(
        run.run_id,
        category=first_category,
        command=_mutation("catalog-first-start"),
    )
    repository.finalize_spot_eligibility_attempt(
        run.run_id,
        category=first_category,
        outcome="SUCCEEDED",
        eligible=True,
        coinbase_api_call_count=1,
        call_count_exact=True,
        portfolio_id_sha256=None,
        **_eligibility_evidence("catalog-first", "SUCCEEDED"),
        command=_mutation("catalog-first-finish"),
    )
    category = "PORTFOLIO_CATALOG"

    repository.start_spot_eligibility_attempt(
        run.run_id,
        category=category,
        command=_mutation("catalog-missing-start"),
    )
    with pytest.raises(AutomationStoreInvalid) as missing:
        repository.finalize_spot_eligibility_attempt(
            run.run_id,
            category=category,
            outcome="SUCCEEDED",
            eligible=True,
            coinbase_api_call_count=1,
            call_count_exact=True,
            portfolio_id_sha256=None,
            **_eligibility_evidence("catalog-missing", "SUCCEEDED"),
            command=_mutation("catalog-missing-finish"),
        )
    assert missing.value.code == "automation_spot_portfolio_binding_required"

    with pytest.raises(AutomationStoreConflict) as mismatch:
        repository.finalize_spot_eligibility_attempt(
            run.run_id,
            category=category,
            outcome="SUCCEEDED",
            eligible=True,
            coinbase_api_call_count=1,
            call_count_exact=True,
            portfolio_id_sha256="f" * 64,
            **_eligibility_evidence("catalog-mismatch", "SUCCEEDED"),
            command=_mutation("catalog-mismatch-finish"),
        )
    assert mismatch.value.code == "automation_spot_portfolio_binding_mismatch"

    bound = repository.finalize_spot_eligibility_attempt(
        run.run_id,
        category=category,
        outcome="SUCCEEDED",
        eligible=True,
        coinbase_api_call_count=1,
        call_count_exact=True,
        portfolio_id_sha256=plan.portfolio_id_sha256,
        **_eligibility_evidence("catalog-bound", "SUCCEEDED"),
        command=_mutation("catalog-bound-finish"),
    ).entity
    assert bound.portfolio_id_sha256 == plan.portfolio_id_sha256

    other_category = "ACCOUNT_WALLET_BALANCES"
    repository.start_spot_eligibility_attempt(
        run.run_id,
        category=other_category,
        command=_mutation("other-binding-start"),
    )
    with pytest.raises(AutomationStoreInvalid) as unrelated:
        repository.finalize_spot_eligibility_attempt(
            run.run_id,
            category=other_category,
            outcome="SUCCEEDED",
            eligible=True,
            coinbase_api_call_count=1,
            call_count_exact=True,
            portfolio_id_sha256=plan.portfolio_id_sha256,
            **_eligibility_evidence("other-binding", "SUCCEEDED"),
            command=_mutation("other-binding-finish"),
        )
    assert unrelated.value.code == "automation_spot_portfolio_binding_forbidden"


def test_schema_migrates_legacy_catalog_attempt_without_inventing_binding(
    repository_harness: _Harness,
):
    repository = repository_harness.repository()
    _, plan, run = _prepare_spot_run(repository, "spot-catalog-migration")
    _allocate_spot_eligibility_cycle(
        repository,
        run.run_id,
        plan.plan_sha256,
        "spot-catalog-migration",
    )
    first_category = AUTOMATION_SPOT_ELIGIBILITY_CATEGORIES[0]
    repository.start_spot_eligibility_attempt(
        run.run_id,
        category=first_category,
        command=_mutation("catalog-migration-first-start"),
    )
    repository.finalize_spot_eligibility_attempt(
        run.run_id,
        category=first_category,
        outcome="SUCCEEDED",
        eligible=True,
        coinbase_api_call_count=1,
        call_count_exact=True,
        portfolio_id_sha256=None,
        **_eligibility_evidence("catalog-migration-first", "SUCCEEDED"),
        command=_mutation("catalog-migration-first-finish"),
    )
    category = "PORTFOLIO_CATALOG"
    repository.start_spot_eligibility_attempt(
        run.run_id,
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
        "observed_at = NOW(), fresh_until = NOW() + INTERVAL '5 minutes', "
        f"evidence_sha256 = '{'a' * 64}', "
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
    assert bound_run.create_call_count == 0
    assert repository.get_spot_live_proof_goal().create_allowance_consumed is True

    finalized = repository.finalize_spot_create_invocation(
        run.run_id,
        outcome=outcome,
        child_terminal=child_terminal,
        coinbase_api_call_count=call_count,
        call_count_exact=call_count_exact,
        read_call_count=(1 if outcome == "ACCEPTED" else (0 if call_count_exact else None)),
        read_call_count_exact=call_count_exact,
        command=_mutation(f"spot-create-{outcome.lower()}-finish"),
    ).entity
    assert finalized.create_outcome == outcome
    assert finalized.create_call_count == call_count
    assert finalized.create_call_count_exact is call_count_exact
    assert repository.get_run(run.run_id).state is run_state


def test_spot_create_accepted_nonterminal_keeps_action_diagnostic_and_serializes_transition_event(
    repository_harness: _Harness,
):
    repository = repository_harness.repository()
    _, _, run = _prepare_spot_run(
        repository,
        "spot-create-active-event-contract",
    )
    _complete_eligible_cycle(
        repository,
        run.run_id,
        "spot-create-active-event-contract-eligibility",
    )
    _await_spot_authorization(
        repository,
        run.run_id,
        "spot-create-active-event-contract",
    )
    repository.start_spot_create_invocation(
        run.run_id,
        eligibility_cycle=1,
        command=_mutation("spot-create-active-event-contract-start"),
    )

    repository.finalize_spot_create_invocation(
        run.run_id,
        outcome="ACCEPTED",
        child_terminal=False,
        coinbase_api_call_count=1,
        call_count_exact=True,
        read_call_count=1,
        read_call_count_exact=True,
        command=_mutation("spot-create-active-event-contract-finish"),
    )

    current = repository.get_run(run.run_id)
    assert current is not None
    assert current.state is OperatorAutomationRunState.ACTIVE
    assert current.diagnostic_code == "automation_spot_safe_closeout_ready"

    service = OperatorAutomationService(
        PostgresOperatorAutomationRepositoryAdapter(repository)
    )
    event_readback = service.list_run_events(
        run_id=run.run_id,
        limit=100,
        offset=0,
    )
    assert event_readback.items[-1].from_state is (
        OperatorAutomationRunState.INVOCATION_STARTED
    )
    assert event_readback.items[-1].state is OperatorAutomationRunState.ACTIVE
    assert event_readback.items[-1].diagnostic_code == (
        "automation_spot_create_accepted_active"
    )


def test_spot_create_unknown_preserves_known_mutation_count(
    repository_harness: _Harness,
):
    repository = repository_harness.repository()
    _, _, run = _prepare_spot_run(repository, "spot-create-known-unknown")
    _complete_eligible_cycle(
        repository,
        run.run_id,
        "spot-create-known-unknown-eligibility",
    )
    _await_spot_authorization(
        repository,
        run.run_id,
        "spot-create-known-unknown",
    )
    repository.start_spot_create_invocation(
        run.run_id,
        eligibility_cycle=1,
        command=_mutation("spot-create-known-unknown-start"),
    )
    repository_harness.database.execute_update(
        f'ALTER TABLE "{repository_harness.schema}".'
        "automation_spot_run_execution "
        "ADD CONSTRAINT automation_spot_create_result_shape_legacy CHECK ("
        "(create_outcome IS NULL AND create_call_count IS NULL "
        "AND NOT create_call_count_exact AND child_terminal IS NULL) OR "
        "(create_outcome = 'ACCEPTED' AND create_call_count_exact "
        "AND create_call_count = 1) OR "
        "(create_outcome = 'REJECTED' AND create_call_count_exact "
        "AND create_call_count IN (0,1)) OR "
        "(create_outcome = 'UNKNOWN' AND NOT create_call_count_exact "
        "AND create_call_count IS NULL))"
    )
    repository.ensure_schema()

    execution = repository.finalize_spot_create_invocation(
        run.run_id,
        outcome="UNKNOWN",
        child_terminal=None,
        coinbase_api_call_count=1,
        call_count_exact=True,
        read_call_count=2,
        read_call_count_exact=True,
        command=_mutation("spot-create-known-unknown-finish"),
    ).entity

    assert execution.create_outcome == "UNKNOWN"
    assert execution.create_call_count == 1
    assert execution.create_call_count_exact is True
    assert execution.create_read_call_count == 2
    current = repository.get_run(run.run_id)
    assert current is not None
    assert current.state is OperatorAutomationRunState.UNKNOWN_CONSUMED
    assert current.coinbase_api_call_count == 3
    assert current.create_call_count == 1


def test_spot_create_start_replay_is_verified_before_consumed_allowance(
    repository_harness: _Harness,
):
    repository = repository_harness.repository()
    _, _, run = _prepare_spot_run(repository, "spot-create-replay-ordering")
    _complete_eligible_cycle(
        repository,
        run.run_id,
        "spot-create-replay-ordering-eligibility",
    )
    _await_spot_authorization(
        repository,
        run.run_id,
        "spot-create-replay-ordering",
    )
    start_command = _mutation("spot-create-replay-ordering-start")
    started = repository.start_spot_create_invocation(
        run.run_id,
        eligibility_cycle=1,
        command=start_command,
    )
    repository.finalize_spot_create_invocation(
        run.run_id,
        outcome="ACCEPTED",
        child_terminal=True,
        coinbase_api_call_count=1,
        call_count_exact=True,
        read_call_count=1,
        read_call_count_exact=True,
        command=_mutation("spot-create-replay-ordering-finish"),
    )

    replay = repository.start_spot_create_invocation(
        run.run_id,
        eligibility_cycle=1,
        command=start_command,
    )
    assert replay.replayed is True
    assert replay.entity == started.entity

    with pytest.raises(AutomationStoreConflict) as changed_payload:
        repository.start_spot_create_invocation(
            run.run_id,
            eligibility_cycle=1,
            command=replace(start_command, payload_sha256="f" * 64),
        )
    assert changed_payload.value.code == "automation_idempotency_conflict"

    with pytest.raises(AutomationStoreConflict) as changed_key:
        repository.start_spot_create_invocation(
            run.run_id,
            eligibility_cycle=1,
            command=_mutation("spot-create-replay-ordering-second"),
        )
    assert changed_key.value.code == "automation_spot_create_allowance_consumed"


def test_spot_known_mutation_and_unknown_read_account_independently(
    repository_harness: _Harness,
):
    repository = repository_harness.repository()
    _, _, run = _prepare_spot_run(repository, "spot-create-known-unknown-read")
    _complete_eligible_cycle(
        repository,
        run.run_id,
        "spot-create-known-unknown-read-eligibility",
    )
    _await_spot_authorization(
        repository,
        run.run_id,
        "spot-create-known-unknown-read",
    )
    repository.start_spot_create_invocation(
        run.run_id,
        eligibility_cycle=1,
        command=_mutation("spot-create-known-unknown-read-start"),
    )

    execution = repository.finalize_spot_create_invocation(
        run.run_id,
        outcome="REJECTED",
        child_terminal=False,
        coinbase_api_call_count=1,
        call_count_exact=True,
        read_call_count=None,
        read_call_count_exact=False,
        command=_mutation("spot-create-known-unknown-read-finish"),
    ).entity

    assert execution.create_call_count == 1
    assert execution.create_call_count_exact is True
    assert execution.create_read_call_count is None
    assert execution.create_read_call_count_exact is False
    current = repository.get_run(run.run_id)
    assert current is not None
    assert current.coinbase_api_call_count == 1
    assert current.create_call_count == 1


def test_spot_create_accepted_requires_one_exact_mutation(
    repository_harness: _Harness,
):
    repository = repository_harness.repository()
    _, _, run = _prepare_spot_run(repository, "spot-create-accepted-zero")
    _complete_eligible_cycle(
        repository,
        run.run_id,
        "spot-create-accepted-zero-eligibility",
    )
    _await_spot_authorization(
        repository,
        run.run_id,
        "spot-create-accepted-zero",
    )
    repository.start_spot_create_invocation(
        run.run_id,
        eligibility_cycle=1,
        command=_mutation("spot-create-accepted-zero-start"),
    )

    with pytest.raises(AutomationStoreInvalid) as invalid:
        repository.finalize_spot_create_invocation(
            run.run_id,
            outcome="ACCEPTED",
            child_terminal=True,
            coinbase_api_call_count=0,
            call_count_exact=True,
            read_call_count=1,
            read_call_count_exact=True,
            command=_mutation("spot-create-accepted-zero-finish"),
        )

    assert invalid.value.code == "automation_spot_mutation_accounting_invalid"
    current = repository.get_run(run.run_id)
    assert current is not None
    assert current.state is OperatorAutomationRunState.INVOCATION_STARTED


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
        read_call_count=1,
        read_call_count_exact=True,
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

    cancel_start_command = _mutation("spot-cancel-start")
    cancelling = repository.start_spot_cancel_invocation(
        run.run_id,
        client_order_id=created.client_order_id,
        command=cancel_start_command,
    ).entity
    assert cancelling.cancel_allowance_consumed is True
    assert repository.get_run(run.run_id).cancel_call_count == 0
    terminal = repository.finalize_spot_cancel_invocation(
        run.run_id,
        outcome="ACCEPTED",
        child_terminal=True,
        coinbase_api_call_count=1,
        call_count_exact=True,
        read_call_count=2,
        read_call_count_exact=True,
        command=_mutation("spot-cancel-finish"),
    ).entity
    assert terminal.cancel_outcome == "ACCEPTED"
    assert terminal.cancel_read_call_count == 2
    assert terminal.cancel_read_call_count_exact is True
    assert terminal.child_terminal is True
    assert repository.get_run(run.run_id).state is OperatorAutomationRunState.TERMINAL

    replay = repository.start_spot_cancel_invocation(
        run.run_id,
        client_order_id=created.client_order_id,
        command=cancel_start_command,
    )
    assert replay.replayed is True
    assert replay.entity == cancelling

    with pytest.raises(AutomationStoreConflict) as changed_payload:
        repository.start_spot_cancel_invocation(
            run.run_id,
            client_order_id=created.client_order_id,
            command=replace(cancel_start_command, payload_sha256="f" * 64),
        )
    assert changed_payload.value.code == "automation_idempotency_conflict"

    with pytest.raises(AutomationStoreConflict) as second_cancel:
        repository.start_spot_cancel_invocation(
            run.run_id,
            client_order_id=created.client_order_id,
            command=_mutation("spot-cancel-second"),
        )
    assert second_cancel.value.code == "automation_spot_cancel_allowance_consumed"


@pytest.mark.parametrize(
    ("posture_action", "expected_posture"),
    [
        ("pause", OperatorAutomationControlPosture.PAUSED),
        ("drain", OperatorAutomationControlPosture.DRAINING),
    ],
)
def test_spot_cancel_claim_remains_available_in_risk_reducing_postures(
    repository_harness: _Harness,
    posture_action: str,
    expected_posture: OperatorAutomationControlPosture,
):
    repository = repository_harness.repository()
    _, _, run = _prepare_spot_run(
        repository,
        f"spot-cancel-{posture_action}",
    )
    _complete_eligible_cycle(
        repository,
        run.run_id,
        f"spot-cancel-{posture_action}-eligibility",
    )
    _await_spot_authorization(
        repository,
        run.run_id,
        f"spot-cancel-{posture_action}",
    )
    created = repository.start_spot_create_invocation(
        run.run_id,
        eligibility_cycle=1,
        command=_mutation(f"spot-cancel-{posture_action}-create-start"),
    ).entity
    repository.finalize_spot_create_invocation(
        run.run_id,
        outcome="ACCEPTED",
        child_terminal=False,
        coinbase_api_call_count=1,
        call_count_exact=True,
        read_call_count=1,
        read_call_count_exact=True,
        command=_mutation(f"spot-cancel-{posture_action}-create-finish"),
    )
    posture = repository.transition_control_posture(
        posture_action,
        _mutation(f"spot-cancel-{posture_action}-posture"),
    ).entity
    assert posture.posture is expected_posture

    claimed = repository.start_spot_cancel_invocation(
        run.run_id,
        client_order_id=created.client_order_id,
        command=_mutation(f"spot-cancel-{posture_action}-start"),
    ).entity

    assert claimed.cancel_allowance_consumed is True
    assert repository.get_spot_live_proof_goal().cancel_allowance_consumed is True


def test_spot_cancel_claim_is_blocked_in_shutdown_without_consuming_allowance(
    repository_harness: _Harness,
):
    repository = repository_harness.repository()
    _, _, run = _prepare_spot_run(repository, "spot-cancel-shutdown")
    _complete_eligible_cycle(
        repository,
        run.run_id,
        "spot-cancel-shutdown-eligibility",
    )
    _await_spot_authorization(repository, run.run_id, "spot-cancel-shutdown")
    created = repository.start_spot_create_invocation(
        run.run_id,
        eligibility_cycle=1,
        command=_mutation("spot-cancel-shutdown-create-start"),
    ).entity
    repository.finalize_spot_create_invocation(
        run.run_id,
        outcome="ACCEPTED",
        child_terminal=False,
        coinbase_api_call_count=1,
        call_count_exact=True,
        read_call_count=1,
        read_call_count_exact=True,
        command=_mutation("spot-cancel-shutdown-create-finish"),
    )
    posture = repository.transition_control_posture(
        "shutdown",
        _mutation("spot-cancel-shutdown-posture"),
    ).entity
    assert posture.posture is OperatorAutomationControlPosture.SHUTDOWN

    with pytest.raises(AutomationStoreConflict) as blocked:
        repository.start_spot_cancel_invocation(
            run.run_id,
            client_order_id=created.client_order_id,
            command=_mutation("spot-cancel-shutdown-start"),
        )

    assert blocked.value.code == "automation_control_plane_shutdown"
    assert repository.get_spot_live_proof_goal().cancel_allowance_consumed is False


def test_spot_safe_closeout_accepts_already_terminal_with_zero_mutation(
    repository_harness: _Harness,
):
    repository = repository_harness.repository()
    _, _, run = _prepare_spot_run(repository, "spot-closeout-already-terminal")
    _complete_eligible_cycle(
        repository,
        run.run_id,
        "spot-closeout-already-terminal-eligibility",
    )
    _await_spot_authorization(
        repository,
        run.run_id,
        "spot-closeout-already-terminal",
    )
    created = repository.start_spot_create_invocation(
        run.run_id,
        eligibility_cycle=1,
        command=_mutation("spot-closeout-already-terminal-create-start"),
    ).entity
    repository.finalize_spot_create_invocation(
        run.run_id,
        outcome="ACCEPTED",
        child_terminal=False,
        coinbase_api_call_count=1,
        call_count_exact=True,
        read_call_count=1,
        read_call_count_exact=True,
        command=_mutation("spot-closeout-already-terminal-create-finish"),
    )
    before_closeout = repository.get_run(run.run_id)
    assert before_closeout is not None

    repository.start_spot_cancel_invocation(
        run.run_id,
        client_order_id=created.client_order_id,
        command=_mutation("spot-closeout-already-terminal-start"),
    )
    repository_harness.database.execute_update(
        f'ALTER TABLE "{repository_harness.schema}".'
        "automation_spot_run_execution "
        "ADD CONSTRAINT automation_spot_safe_closeout_result_shape_legacy "
        "CHECK (cancel_outcome IS NULL OR "
        "(cancel_outcome = 'ACCEPTED' AND cancel_call_count_exact "
        "AND cancel_call_count = 1) OR "
        "(cancel_outcome = 'REJECTED' AND cancel_call_count_exact "
        "AND cancel_call_count IN (0,1)) OR "
        "(cancel_outcome = 'UNKNOWN' AND NOT cancel_call_count_exact "
        "AND cancel_call_count IS NULL))"
    )
    repository.ensure_schema()
    execution = repository.finalize_spot_cancel_invocation(
        run.run_id,
        outcome="ACCEPTED",
        child_terminal=True,
        coinbase_api_call_count=0,
        call_count_exact=True,
        read_call_count=1,
        read_call_count_exact=True,
        command=_mutation("spot-closeout-already-terminal-finish"),
    ).entity

    assert execution.cancel_outcome == "ACCEPTED"
    assert execution.cancel_call_count == 0
    assert execution.cancel_call_count_exact is True
    current = repository.get_run(run.run_id)
    assert current is not None
    assert current.state is OperatorAutomationRunState.TERMINAL
    assert current.cancel_call_count == 0
    assert current.coinbase_api_call_count == (
        before_closeout.coinbase_api_call_count + 1
    )


def test_spot_cancel_requires_exact_create_readback(
    repository_harness: _Harness,
):
    repository = repository_harness.repository()
    _, _, run = _prepare_spot_run(repository, "spot-create-readback-required")
    _complete_eligible_cycle(
        repository,
        run.run_id,
        "spot-create-readback-required-eligibility",
    )
    _await_spot_authorization(
        repository,
        run.run_id,
        "spot-create-readback-required",
    )
    created = repository.start_spot_create_invocation(
        run.run_id,
        eligibility_cycle=1,
        command=_mutation("spot-create-readback-required-start"),
    ).entity
    execution = repository.finalize_spot_create_invocation(
        run.run_id,
        outcome="ACCEPTED",
        child_terminal=False,
        coinbase_api_call_count=1,
        call_count_exact=True,
        read_call_count=0,
        read_call_count_exact=True,
        command=_mutation("spot-create-readback-required-finish"),
    ).entity
    assert execution.create_read_call_count == 0
    assert execution.create_read_call_count_exact is True

    with pytest.raises(AutomationStoreConflict) as missing_readback:
        repository.start_spot_cancel_invocation(
            run.run_id,
            client_order_id=created.client_order_id,
            command=_mutation("spot-create-readback-required-cancel"),
        )
    assert missing_readback.value.code == (
        "automation_spot_cancel_create_readback_required"
    )
    assert repository.get_spot_live_proof_goal().cancel_allowance_consumed is False


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
        read_call_count=1,
        read_call_count_exact=True,
        command=_mutation("spot-active-restart-create-finish"),
    )

    restarted = repository_harness.repository()
    assert restarted.recover_runs_after_restart() == ()
    active = restarted.get_run(run.run_id)
    assert active is not None
    assert active.state is OperatorAutomationRunState.ACTIVE
    assert active.diagnostic_code == "automation_spot_safe_closeout_ready"

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


def _seal_rejected_predecessor(
    repository: OperatorAutomationRepository,
    seed: str,
):
    definition, plan, run = _prepare_spot_run(repository, seed)
    _complete_eligible_cycle(repository, run.run_id, f"{seed}-eligibility")
    repository.start_spot_create_invocation(
        run.run_id,
        eligibility_cycle=1,
        command=_mutation(f"{seed}-create-start"),
    )
    repository.finalize_spot_create_invocation(
        run.run_id,
        outcome="REJECTED",
        child_terminal=False,
        coinbase_api_call_count=1,
        call_count_exact=True,
        read_call_count=0,
        read_call_count_exact=True,
        command=_mutation(f"{seed}-create-finish"),
    )
    return definition, plan, run


def test_preview_gated_successor_uses_distinct_goal_and_preserves_predecessor_rows(
    repository_harness: _Harness,
):
    repository = repository_harness.repository()
    predecessor = _seal_rejected_predecessor(repository, "preview-successor")
    predecessor_tables = (
        "automation_definition",
        "automation_spot_single_child_plan",
        "automation_run",
        "automation_spot_eligibility_cycle",
        "automation_spot_eligibility_attempt",
        "automation_spot_run_execution",
        "automation_spot_live_proof_goal",
        "automation_event_outbox",
    )
    before = {
        table: repository_harness.rows(
            f'SELECT * FROM "{repository_harness.schema}".{table} ORDER BY 1'
        )
        for table in predecessor_tables
    }

    successor = repository.create_definition(
        _definition_command(
            "preview-successor-v2",
            product_ids=("BTC-USDC",),
        ),
        spot_single_child_plan=_spot_plan_terms(),
        spot_goal_key=AUTOMATION_SPOT_PREVIEW_GATED_GOAL_KEY,
    ).entity

    assert successor.definition_id != predecessor[0].definition_id
    assert repository.has_spot_single_child_run() is True
    assert repository.has_spot_single_child_run(
        goal_key=AUTOMATION_SPOT_PREVIEW_GATED_GOAL_KEY
    ) is False
    assert repository.get_spot_goal_key_for_definition(successor.definition_id) == (
        AUTOMATION_SPOT_PREVIEW_GATED_GOAL_KEY
    )
    assert repository.get_spot_goal_key_for_definition(
        predecessor[0].definition_id
    ) != AUTOMATION_SPOT_PREVIEW_GATED_GOAL_KEY
    goal = repository.get_spot_preview_gated_goal()
    assert goal.definition_id == successor.definition_id
    assert goal.preview_allowance_consumed is False
    assert goal.create_allowance_consumed is False
    assert goal.cancel_allowance_consumed is False

    enabled = repository.transition_definition(
        successor.definition_id,
        "enable",
        _mutation("preview-successor-v2-enable"),
    ).entity
    repository.claim_one_shot_run(
        enabled.definition_id,
        _mutation("preview-successor-v2-run"),
    )
    assert repository.has_spot_single_child_run(
        goal_key=AUTOMATION_SPOT_PREVIEW_GATED_GOAL_KEY
    ) is True
    for table, rows in before.items():
        current = repository_harness.rows(
            f'SELECT * FROM "{repository_harness.schema}".{table} ORDER BY 1'
        )
        assert all(row in current for row in rows)

    with pytest.raises(AutomationStoreConflict) as second_successor:
        repository.create_definition(
            _definition_command(
                "preview-successor-v2-duplicate",
                product_ids=("BTC-USDC",),
            ),
            spot_single_child_plan=_spot_plan_terms(),
            spot_goal_key=AUTOMATION_SPOT_PREVIEW_GATED_GOAL_KEY,
        )
    assert second_successor.value.code == (
        "automation_spot_preview_successor_definition_already_exists"
    )


def test_documented_market_freshness_v3_requires_terminal_v2_and_preserves_it(
    repository_harness: _Harness,
):
    repository = repository_harness.repository()
    _seal_rejected_predecessor(repository, "documented-freshness-v1")
    v2 = repository.create_definition(
        _definition_command(
            "documented-freshness-v2",
            product_ids=("BTC-USDC",),
        ),
        spot_single_child_plan=_spot_plan_terms(),
        spot_goal_key=AUTOMATION_SPOT_PREVIEW_GATED_GOAL_KEY,
    ).entity

    with pytest.raises(AutomationStoreConflict) as premature:
        repository.create_definition(
            _definition_command(
                "documented-freshness-v3-premature",
                product_ids=("BTC-USDC",),
            ),
            spot_single_child_plan=_spot_plan_terms(
                base_size="0.00001",
                submitted_notional_usdc="0.50",
                possible_execution_notional_usdc="0.50",
            ),
            spot_goal_key=AUTOMATION_SPOT_DOCUMENTED_MARKET_FRESHNESS_GOAL_KEY,
        )
    assert premature.value.code == (
        "automation_spot_documented_freshness_predecessor_not_terminal"
    )

    enabled = repository.transition_definition(
        v2.definition_id,
        "enable",
        _mutation("documented-freshness-v2-enable"),
    ).entity
    v2_run = repository.claim_one_shot_run(
        enabled.definition_id,
        _mutation("documented-freshness-v2-run"),
    ).entity
    repository.transition_run(
        v2_run.run_id,
        OperatorAutomationRunState.BLOCKED,
        diagnostic_code="automation_run_blocked",
        command=_mutation("documented-freshness-v2-terminal"),
    )
    preserved_tables = (
        "automation_definition",
        "automation_spot_single_child_plan",
        "automation_spot_plan_goal",
        "automation_run",
        "automation_spot_preview_gated_goal",
        "automation_event_outbox",
    )
    before = {
        table: repository_harness.rows(
            f'SELECT * FROM "{repository_harness.schema}".{table}'
            + (
                " WHERE goal_key <> %s"
                if table == "automation_spot_preview_gated_goal"
                else ""
            )
            + " ORDER BY 1",
            (
                (AUTOMATION_SPOT_DOCUMENTED_MARKET_FRESHNESS_GOAL_KEY,)
                if table == "automation_spot_preview_gated_goal"
                else ()
            ),
        )
        for table in preserved_tables
    }

    v3 = repository.create_definition(
        _definition_command(
            "documented-freshness-v3",
            product_ids=("BTC-USDC",),
        ),
        spot_single_child_plan=_spot_plan_terms(
            base_size="0.00001",
            submitted_notional_usdc="0.50",
            possible_execution_notional_usdc="0.50",
        ),
        spot_goal_key=AUTOMATION_SPOT_DOCUMENTED_MARKET_FRESHNESS_GOAL_KEY,
    ).entity

    assert v3.definition_id != v2.definition_id
    assert repository.get_spot_goal_key_for_definition(v3.definition_id) == (
        AUTOMATION_SPOT_DOCUMENTED_MARKET_FRESHNESS_GOAL_KEY
    )
    v2_goal = repository.get_spot_preview_gated_goal(
        goal_key=AUTOMATION_SPOT_PREVIEW_GATED_GOAL_KEY,
    )
    v3_goal = repository.get_spot_preview_gated_goal(
        goal_key=AUTOMATION_SPOT_DOCUMENTED_MARKET_FRESHNESS_GOAL_KEY,
    )
    assert v2_goal.definition_id == v2.definition_id
    assert v3_goal.definition_id == v3.definition_id
    assert v3_goal.preview_allowance_consumed is False
    assert v3_goal.create_allowance_consumed is False
    assert v3_goal.cancel_allowance_consumed is False
    for table, rows in before.items():
        current = repository_harness.rows(
            f'SELECT * FROM "{repository_harness.schema}".{table}'
            + (
                " WHERE goal_key <> %s"
                if table == "automation_spot_preview_gated_goal"
                else ""
            )
            + " ORDER BY 1",
            (
                (AUTOMATION_SPOT_DOCUMENTED_MARKET_FRESHNESS_GOAL_KEY,)
                if table == "automation_spot_preview_gated_goal"
                else ()
            ),
        )
        assert all(row in current for row in rows)

    v2_goal_before_v3_attempt = repository.get_spot_preview_gated_goal(
        goal_key=AUTOMATION_SPOT_PREVIEW_GATED_GOAL_KEY,
    )
    enabled_v3 = repository.transition_definition(
        v3.definition_id,
        "enable",
        _mutation("documented-freshness-v3-enable"),
    ).entity
    v3_run = repository.claim_one_shot_run(
        enabled_v3.definition_id,
        _mutation("documented-freshness-v3-run"),
    ).entity
    repository.transition_run(
        v3_run.run_id,
        OperatorAutomationRunState.PREPARING,
        diagnostic_code="preparing",
        command=_mutation("documented-freshness-v3-preparing"),
    )
    _reject_v3_cycle_for_missing_market_observation(
        repository,
        v3_run.run_id,
        "documented-freshness-v3-missing-market-time",
    )
    repository = repository_harness.repository()
    persisted_v3_cycle = repository.list_spot_eligibility_cycles(
        goal_key=AUTOMATION_SPOT_DOCUMENTED_MARKET_FRESHNESS_GOAL_KEY,
    )[-1]
    persisted_v3_market_attempt = next(
        attempt
        for attempt in repository.list_spot_eligibility_attempts(
            v3_run.run_id,
            cycle_number=persisted_v3_cycle.cycle_number,
        )
        if attempt.category == "BEST_BID_ASK"
    )
    assert persisted_v3_cycle.state == "REJECTED"
    assert persisted_v3_cycle.call_count_exact is True
    assert persisted_v3_cycle.fresh_until is None
    assert persisted_v3_market_attempt.outcome == "REJECTED"
    assert persisted_v3_market_attempt.coinbase_api_call_count == 1
    assert persisted_v3_market_attempt.call_count_exact is True
    assert persisted_v3_market_attempt.observed_at is None
    assert persisted_v3_market_attempt.fresh_until is None
    assert persisted_v3_market_attempt.evidence_sha256 is None
    _complete_eligible_cycle(
        repository,
        v3_run.run_id,
        "documented-freshness-v3-cycle",
    )
    repository.start_spot_preview_invocation(
        v3_run.run_id,
        eligibility_cycle=2,
        command=_mutation("documented-freshness-v3-preview-start"),
    )
    terminal_v3_goal = repository.finalize_spot_preview_invocation(
        v3_run.run_id,
        outcome="REJECTED",
        failure_class="DOCUMENTED_REJECTION",
        rejection_code=None,
        warning_present=False,
        preview_id_sha256=None,
        preview_call_count=1,
        call_count_exact=True,
        command=_mutation("documented-freshness-v3-preview-finish"),
    ).entity

    assert terminal_v3_goal.goal_key == (
        AUTOMATION_SPOT_DOCUMENTED_MARKET_FRESHNESS_GOAL_KEY
    )
    assert terminal_v3_goal.preview_allowance_consumed is True
    assert terminal_v3_goal.preview_outcome == "REJECTED"
    assert terminal_v3_goal.create_allowance_consumed is False
    assert repository.get_spot_preview_gated_goal(
        goal_key=AUTOMATION_SPOT_PREVIEW_GATED_GOAL_KEY,
    ) == v2_goal_before_v3_attempt


def _seal_rejected_v3_predecessor(
    repository: OperatorAutomationRepository,
    seed: str,
) -> None:
    _seal_rejected_predecessor(repository, f"{seed}-v1")
    v2 = repository.create_definition(
        _definition_command(f"{seed}-v2", product_ids=("BTC-USDC",)),
        spot_single_child_plan=_spot_plan_terms(),
        spot_goal_key=AUTOMATION_SPOT_PREVIEW_GATED_GOAL_KEY,
    ).entity
    v2 = repository.transition_definition(
        v2.definition_id,
        "enable",
        _mutation(f"{seed}-v2-enable"),
    ).entity
    v2_run = repository.claim_one_shot_run(
        v2.definition_id,
        _mutation(f"{seed}-v2-run"),
    ).entity
    repository.transition_run(
        v2_run.run_id,
        OperatorAutomationRunState.BLOCKED,
        diagnostic_code="automation_run_blocked",
        command=_mutation(f"{seed}-v2-terminal"),
    )
    v3 = repository.create_definition(
        _definition_command(f"{seed}-v3", product_ids=("BTC-USDC",)),
        spot_single_child_plan=_spot_plan_terms(
            base_size="0.00001",
            submitted_notional_usdc="0.50",
            possible_execution_notional_usdc="0.50",
        ),
        spot_goal_key=AUTOMATION_SPOT_DOCUMENTED_MARKET_FRESHNESS_GOAL_KEY,
    ).entity
    v3 = repository.transition_definition(
        v3.definition_id,
        "enable",
        _mutation(f"{seed}-v3-enable"),
    ).entity
    v3_run = repository.claim_one_shot_run(
        v3.definition_id,
        _mutation(f"{seed}-v3-run"),
    ).entity
    repository.transition_run(
        v3_run.run_id,
        OperatorAutomationRunState.PREPARING,
        diagnostic_code="preparing",
        command=_mutation(f"{seed}-v3-preparing"),
    )
    _complete_eligible_cycle(repository, v3_run.run_id, f"{seed}-v3-cycle")
    repository.start_spot_preview_invocation(
        v3_run.run_id,
        eligibility_cycle=1,
        command=_mutation(f"{seed}-v3-preview-start"),
    )
    repository.finalize_spot_preview_invocation(
        v3_run.run_id,
        outcome="REJECTED",
        failure_class="DOCUMENTED_REJECTION",
        rejection_code="LIMIT_PRICE",
        warning_present=False,
        preview_id_sha256=None,
        preview_call_count=1,
        call_count_exact=True,
        command=_mutation(f"{seed}-v3-preview-finish"),
    )


def test_near_market_definition_cannot_bypass_claimed_materialization(
    repository_harness: _Harness,
) -> None:
    repository = repository_harness.repository()
    _seal_rejected_v3_predecessor(repository, "near-market-bypass")

    with pytest.raises(AutomationStoreInvalid) as error:
        repository.create_definition(
            _definition_command(
                "near-market-bypass-v4",
                product_ids=("BTC-USDC",),
            ),
            spot_single_child_plan=_spot_plan_terms(
                base_size="0.00001",
                limit_price="49999",
                submitted_notional_usdc="0.49999",
                possible_execution_notional_usdc="0.49999",
                post_only=True,
            ),
            spot_goal_key=AUTOMATION_SPOT_NEAR_MARKET_V4_GOAL_KEY,
        )

    assert error.value.code == "automation_near_market_materialization_required"


def test_near_market_preparation_claim_atomically_materializes_v4_post_only_plan(
    repository_harness: _Harness,
) -> None:
    repository = repository_harness.repository()
    _seal_rejected_v3_predecessor(repository, "near-market")
    claim_command = _mutation("near-market-v4-preparation")
    claimed = repository.start_spot_near_market_preparation(claim_command)
    assert claimed.entity.goal_key == AUTOMATION_SPOT_NEAR_MARKET_V4_GOAL_KEY
    assert claimed.entity.candidate_version == 4
    assert claimed.entity.cycle_number == 1
    assert claimed.entity.state == "CLAIMED"
    with pytest.raises(
        psycopg2.errors.RaiseException,
        match="automation_spot_near_market_preparation_binding_is_immutable",
    ):
        with repository.database.get_cursor() as cursor:
            cursor.execute(
                f'UPDATE "{repository.schema}".'
                "automation_spot_near_market_preparation "
                "SET correlation_id = 'tampered-correlation' "
                "WHERE cycle_number = %s",
                (claimed.entity.cycle_number,),
            )

    terms = _spot_plan_terms(
        base_size="0.00001",
        limit_price="49999",
        submitted_notional_usdc="0.49999",
        possible_execution_notional_usdc="0.49999",
        post_only=True,
    )
    with pytest.raises(AutomationStoreInvalid) as unbound_evidence:
        repository.create_definition(
            _definition_command(
                "near-market-v4-definition-unbound",
                product_ids=("BTC-USDC",),
            ),
            spot_single_child_plan=terms,
            spot_goal_key=AUTOMATION_SPOT_NEAR_MARKET_V4_GOAL_KEY,
            spot_near_market_materialization=(
                AutomationSpotNearMarketMaterializationEvidence(
                    cycle_number=claimed.entity.cycle_number,
                    goal_key=claimed.entity.goal_key,
                    diagnostic_code="automation_near_market_terms_derived",
                    completed_categories=tuple(
                        AUTOMATION_SPOT_ELIGIBILITY_CATEGORIES[:6]
                    ),
                    coinbase_api_call_count=6,
                    evidence_sha256="f" * 64,
                )
            ),
        )
    assert unbound_evidence.value.code == (
        "automation_near_market_materialization_invalid"
    )
    with pytest.raises(AutomationStoreInvalid) as portfolio_drift:
        repository.create_definition(
            _definition_command(
                "near-market-v4-definition-portfolio-drift",
                product_ids=("BTC-USDC",),
            ),
            spot_single_child_plan=replace(
                terms,
                portfolio_id_sha256="b" * 64,
            ),
            spot_goal_key=AUTOMATION_SPOT_NEAR_MARKET_V4_GOAL_KEY,
            spot_near_market_materialization=(
                _near_market_materialization_evidence(
                    terms,
                    cycle_number=claimed.entity.cycle_number,
                    goal_key=claimed.entity.goal_key,
                )
            ),
        )
    assert portfolio_drift.value.code == (
        "automation_near_market_materialization_invalid"
    )
    created = repository.create_definition(
        _definition_command(
            "near-market-v4-definition",
            product_ids=("BTC-USDC",),
        ),
        spot_single_child_plan=terms,
        spot_goal_key=AUTOMATION_SPOT_NEAR_MARKET_V4_GOAL_KEY,
        spot_near_market_materialization=_near_market_materialization_evidence(
            terms,
            cycle_number=claimed.entity.cycle_number,
            goal_key=claimed.entity.goal_key,
        ),
    )
    plan = repository.get_spot_single_child_plan(
        created.entity.definition_id,
        created.entity.revision,
    )
    assert plan is not None and plan.post_only is True
    finalized = repository.list_spot_near_market_preparations()
    assert len(finalized) == 1
    assert finalized[0].state == "MATERIALIZED"
    assert finalized[0].definition_id == created.entity.definition_id
    assert finalized[0].coinbase_api_call_count == 6
    with pytest.raises(
        psycopg2.errors.RaiseException,
        match="automation_spot_near_market_preparation_is_immutable",
    ):
        with repository.database.get_cursor() as cursor:
            cursor.execute(
                f'DELETE FROM "{repository.schema}".'
                "automation_spot_near_market_preparation "
                "WHERE cycle_number = %s",
                (claimed.entity.cycle_number,),
            )
    assert repository.start_spot_near_market_preparation(
        claim_command
    ).entity == finalized[0]
    with pytest.raises(AutomationStoreConflict) as correlation_conflict:
        repository.start_spot_near_market_preparation(
            replace(
                claim_command,
                correlation_id="correlation-near-market-v4-preparation-drift",
            )
        )
    assert correlation_conflict.value.code == (
        "automation_near_market_preparation_idempotency_conflict"
    )

    enabled = repository.transition_definition(
        created.entity.definition_id,
        "enable",
        _mutation("near-market-v4-enable"),
    ).entity
    run = repository.claim_one_shot_run(
        enabled.definition_id,
        _mutation("near-market-v4-run"),
    ).entity
    repository.transition_run(
        run.run_id,
        OperatorAutomationRunState.PREPARING,
        diagnostic_code="preparing",
        command=_mutation("near-market-v4-preparing"),
    )
    _complete_eligible_cycle(repository, run.run_id, "near-market-v4-cycle")
    cycle = repository.list_spot_eligibility_cycles(
        goal_key=AUTOMATION_SPOT_NEAR_MARKET_V4_GOAL_KEY,
    )[-1]
    assert cycle.policy_revision == 3
    repository.start_spot_preview_invocation(
        run.run_id,
        eligibility_cycle=cycle.cycle_number,
        command=_mutation("near-market-v4-preview-start"),
    )
    repository.finalize_spot_preview_invocation(
        run.run_id,
        outcome="ACCEPTED",
        failure_class="NONE",
        rejection_code=None,
        warning_present=False,
        preview_id_sha256="a" * 64,
        preview_call_count=1,
        call_count_exact=True,
        command=_mutation("near-market-v4-preview-finish"),
    )
    started = repository.start_spot_create_invocation(
        run.run_id,
        eligibility_cycle=cycle.cycle_number,
        command=_mutation("near-market-v4-create-start"),
    )
    assert started.entity.policy_revision == 3
    repository.finalize_spot_create_invocation(
        run.run_id,
        outcome="ACCEPTED",
        child_terminal=False,
        coinbase_api_call_count=1,
        call_count_exact=True,
        read_call_count=1,
        read_call_count_exact=True,
        command=_mutation("near-market-v4-create-finish"),
    )
    repository.start_spot_cancel_invocation(
        run.run_id,
        client_order_id=started.entity.client_order_id,
        command=_mutation("near-market-v4-cancel-start"),
    )
    repository.finalize_spot_cancel_invocation(
        run.run_id,
        outcome="ACCEPTED",
        child_terminal=True,
        coinbase_api_call_count=1,
        call_count_exact=True,
        read_call_count=2,
        read_call_count_exact=True,
        command=_mutation("near-market-v4-cancel-finish"),
    )
    terminal = repository.get_run(run.run_id)
    assert terminal is not None
    assert terminal.state is OperatorAutomationRunState.TERMINAL


def test_minimum_size_v7_has_a_distinct_ledger_and_atomic_dynamic_cap_plan(
    repository_harness: _Harness,
) -> None:
    repository = repository_harness.repository()
    _seal_rejected_v3_predecessor(repository, "minimum-size")
    v4 = repository.start_spot_near_market_preparation(
        _mutation("minimum-size-v4-preparation")
    ).entity
    v4_evidence = near_market_preparation_evidence_sha256(
        call_count=6,
        categories=AUTOMATION_SPOT_ELIGIBILITY_CATEGORIES[:6],
        diagnostic_code="near_market_no_valid_size",
        outcome="BLOCKED",
        policy_revision=NEAR_MARKET_POLICY_REVISION,
        plan=None,
    )
    repository.finalize_spot_near_market_preparation(
        cycle_number=v4.cycle_number,
        goal_key=v4.goal_key,
        state="BLOCKED",
        diagnostic_code="near_market_no_valid_size",
        completed_categories=tuple(AUTOMATION_SPOT_ELIGIBILITY_CATEGORIES[:6]),
        coinbase_api_call_count=6,
        call_count_exact=True,
        evidence_sha256=v4_evidence,
        definition_id=None,
    )

    claimed = repository.start_spot_minimum_size_preparation(
        _mutation("minimum-size-v7-preparation")
    )
    assert claimed.entity.goal_key == AUTOMATION_SPOT_MINIMUM_SIZE_V7_GOAL_KEY
    assert claimed.entity.candidate_version == 7
    assert claimed.entity.cycle_number == 1
    assert claimed.entity.state == "CLAIMED"
    assert len(repository.list_spot_near_market_preparations()) == 1

    with pytest.raises(AutomationStoreInvalid) as mismatched_unknown_stage:
        repository.finalize_spot_minimum_size_preparation(
            cycle_number=claimed.entity.cycle_number,
            goal_key=claimed.entity.goal_key,
            state="UNKNOWN",
            diagnostic_code=(
                "automation_minimum_size_portfolio_catalog_unknown"
            ),
            completed_categories=(),
            coinbase_api_call_count=None,
            call_count_exact=False,
            evidence_sha256=None,
            definition_id=None,
        )
    assert mismatched_unknown_stage.value.code == (
        "automation_minimum_size_preparation_result_invalid"
    )

    with pytest.raises(AutomationStoreInvalid) as mismatched_blocked_evidence:
        repository.finalize_spot_minimum_size_preparation(
            cycle_number=claimed.entity.cycle_number,
            goal_key=claimed.entity.goal_key,
            state="BLOCKED",
            diagnostic_code="minimum_size_wallet_insufficient",
            completed_categories=tuple(
                AUTOMATION_SPOT_ELIGIBILITY_CATEGORIES[:6]
            ),
            coinbase_api_call_count=6,
            call_count_exact=True,
            evidence_sha256="a" * 64,
            definition_id=None,
        )
    assert mismatched_blocked_evidence.value.code == (
        "automation_minimum_size_preparation_result_invalid"
    )

    terms = _spot_plan_terms(
        base_size="0.00001",
        limit_price="100000",
        submitted_notional_usdc="1",
        possible_execution_notional_usdc="1",
        max_possible_execution_notional_usdc="1.01",
        post_only=True,
    )
    created = repository.create_definition(
        _definition_command(
            "minimum-size-v7-definition",
            product_ids=("BTC-USDC",),
        ),
        spot_single_child_plan=terms,
        spot_goal_key=AUTOMATION_SPOT_MINIMUM_SIZE_V7_GOAL_KEY,
        spot_minimum_size_materialization=(
            _minimum_size_materialization_evidence(
                terms,
                cycle_number=claimed.entity.cycle_number,
                goal_key=claimed.entity.goal_key,
            )
        ),
    )
    stored_plan = repository.get_spot_single_child_plan(
        created.entity.definition_id,
        created.entity.revision,
    )
    assert stored_plan is not None
    assert stored_plan.max_possible_execution_notional_usdc == "1.01"
    prepared = repository.list_spot_minimum_size_preparations()
    assert len(prepared) == 1
    assert prepared[0].state == "MATERIALIZED"
    assert prepared[0].definition_id == created.entity.definition_id

    enabled = repository.transition_definition(
        created.entity.definition_id,
        "enable",
        _mutation("minimum-size-v7-enable"),
    ).entity
    run = repository.claim_one_shot_run(
        enabled.definition_id,
        _mutation("minimum-size-v7-run"),
    ).entity
    repository.transition_run(
        run.run_id,
        OperatorAutomationRunState.PREPARING,
        diagnostic_code="preparing",
        command=_mutation("minimum-size-v7-preparing"),
    )
    _complete_eligible_cycle(repository, run.run_id, "minimum-size-v7-cycle")
    cycle = repository.list_spot_eligibility_cycles(
        goal_key=AUTOMATION_SPOT_MINIMUM_SIZE_V7_GOAL_KEY,
    )[-1]
    assert cycle.policy_revision == 4

    with pytest.raises(AutomationStoreConflict) as blocked_v8:
        repository.start_spot_minimum_size_preparation(
            _mutation("minimum-size-v8-too-early")
        )
    assert blocked_v8.value.code == "automation_minimum_size_successor_not_available"
    assert repository.list_spot_eligibility_cycles(
        goal_key=AUTOMATION_SPOT_MINIMUM_SIZE_V8_GOAL_KEY,
    ) == ()
    assert repository.list_spot_eligibility_cycles(
        goal_key=AUTOMATION_SPOT_MINIMUM_SIZE_V9_GOAL_KEY,
    ) == ()

    repository.start_spot_preview_invocation(
        run.run_id,
        eligibility_cycle=cycle.cycle_number,
        command=_mutation("minimum-size-v7-preview-start"),
    )
    repository.finalize_spot_preview_invocation(
        run.run_id,
        outcome="ACCEPTED",
        failure_class="NONE",
        rejection_code=None,
        warning_present=False,
        preview_id_sha256="a" * 64,
        preview_call_count=1,
        call_count_exact=True,
        command=_mutation("minimum-size-v7-preview-finish"),
    )
    started = repository.start_spot_create_invocation(
        run.run_id,
        eligibility_cycle=cycle.cycle_number,
        command=_mutation("minimum-size-v7-create-start"),
    )
    assert started.entity.policy_revision == 4
    repository.finalize_spot_create_invocation(
        run.run_id,
        outcome="ACCEPTED",
        child_terminal=False,
        coinbase_api_call_count=1,
        call_count_exact=True,
        read_call_count=1,
        read_call_count_exact=True,
        command=_mutation("minimum-size-v7-create-finish"),
    )
    repository.start_spot_cancel_invocation(
        run.run_id,
        client_order_id=started.entity.client_order_id,
        command=_mutation("minimum-size-v7-cancel-start"),
    )
    repository.finalize_spot_cancel_invocation(
        run.run_id,
        outcome="ACCEPTED",
        child_terminal=True,
        coinbase_api_call_count=1,
        call_count_exact=True,
        read_call_count=2,
        read_call_count_exact=True,
        command=_mutation("minimum-size-v7-cancel-finish"),
    )
    with pytest.raises(AutomationStoreConflict) as accepted_stops_successors:
        repository.start_spot_minimum_size_preparation(
            _mutation("minimum-size-v8-after-accepted-preview")
        )
    assert accepted_stops_successors.value.code == (
        "automation_minimum_size_successor_not_available"
    )


def test_minimum_size_v7_v9_sequence_preserves_distinct_terminal_outcomes(
    repository_harness: _Harness,
) -> None:
    repository = repository_harness.repository()
    _seal_minimum_size_predecessor(repository, "minimum-size-sequence")
    expected = (
        (7, AUTOMATION_SPOT_MINIMUM_SIZE_V7_GOAL_KEY, "REJECTED"),
        (8, AUTOMATION_SPOT_MINIMUM_SIZE_V8_GOAL_KEY, "UNKNOWN"),
        (9, AUTOMATION_SPOT_MINIMUM_SIZE_V9_GOAL_KEY, "ACCEPTED"),
    )

    for version, goal_key, outcome in expected:
        claimed, _definition, run = _materialize_minimum_size_candidate(
            repository,
            f"minimum-size-sequence-v{version}",
        )
        assert claimed.candidate_version == version
        assert claimed.goal_key == goal_key
        _complete_eligible_cycle(
            repository,
            run.run_id,
            f"minimum-size-sequence-v{version}-eligibility",
        )
        cycle = repository.list_spot_eligibility_cycles(goal_key=goal_key)[-1]
        repository.start_spot_preview_invocation(
            run.run_id,
            eligibility_cycle=cycle.cycle_number,
            command=_mutation(f"minimum-size-v{version}-preview-start"),
        )
        repository.finalize_spot_preview_invocation(
            run.run_id,
            outcome=outcome,
            failure_class={
                "REJECTED": "DOCUMENTED_REJECTION",
                "UNKNOWN": "TRANSPORT_UNKNOWN",
                "ACCEPTED": "NONE",
            }[outcome],
            rejection_code=(
                "BASE_SIZE_TOO_SMALL" if outcome == "REJECTED" else None
            ),
            warning_present=False,
            preview_id_sha256=("b" * 64 if outcome == "ACCEPTED" else None),
            preview_call_count=(None if outcome == "UNKNOWN" else 1),
            call_count_exact=outcome != "UNKNOWN",
            command=_mutation(f"minimum-size-v{version}-preview-finish"),
        )
        goal = repository.get_spot_preview_gated_goal(goal_key=goal_key)
        assert goal.preview_allowance_consumed is True
        assert goal.preview_outcome == outcome
        assert goal.create_allowance_consumed is False

    with pytest.raises(AutomationStoreConflict) as no_v10:
        repository.start_spot_minimum_size_preparation(
            _mutation("minimum-size-v10-forbidden")
        )
    assert no_v10.value.code == "automation_minimum_size_successor_not_available"


def test_minimum_size_preparation_restart_consumes_unknown_cycle(
    repository_harness: _Harness,
) -> None:
    repository = repository_harness.repository()
    _seal_minimum_size_predecessor(repository, "minimum-size-restart")
    claimed = repository.start_spot_minimum_size_preparation(
        _mutation("minimum-size-restart-v7")
    ).entity

    restarted = repository_harness.repository()
    restarted.recover_runs_after_restart()

    recovered = restarted.list_spot_minimum_size_preparations()
    assert len(recovered) == 1
    assert recovered[0].cycle_number == claimed.cycle_number
    assert recovered[0].state == "UNKNOWN"
    assert recovered[0].definition_id is None
    assert recovered[0].coinbase_api_call_count is None
    assert recovered[0].call_count_exact is False
    assert recovered[0].evidence_sha256 is None
    next_claim = restarted.start_spot_minimum_size_preparation(
        _mutation("minimum-size-restart-v7-next")
    ).entity
    assert next_claim.goal_key == AUTOMATION_SPOT_MINIMUM_SIZE_V7_GOAL_KEY
    assert next_claim.cycle_number == claimed.cycle_number + 1


def test_concurrent_minimum_size_preparation_has_one_claimant(
    repository_harness: _Harness,
) -> None:
    repository = repository_harness.repository()
    _seal_minimum_size_predecessor(repository, "minimum-size-concurrent")
    barrier = threading.Barrier(2)
    results: list = []
    failures: list[Exception] = []
    lock = threading.Lock()

    def claim(index: int) -> None:
        candidate_repository = repository_harness.repository()
        barrier.wait()
        try:
            result = candidate_repository.start_spot_minimum_size_preparation(
                _mutation(f"minimum-size-concurrent-{index}")
            )
            with lock:
                results.append(result)
        except Exception as exc:  # pragma: no cover - asserted below
            with lock:
                failures.append(exc)

    threads = [threading.Thread(target=claim, args=(index,)) for index in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert all(not thread.is_alive() for thread in threads)
    assert len(results) == 1
    assert results[0].entity.state == "CLAIMED"
    assert len(failures) == 1
    assert isinstance(failures[0], AutomationStoreConflict)
    assert failures[0].code == "automation_minimum_size_preparation_in_progress"


def test_minimum_size_preparation_and_eligibility_share_ten_cycle_budget(
    repository_harness: _Harness,
) -> None:
    repository = repository_harness.repository()
    _seal_minimum_size_predecessor(repository, "minimum-size-global-budget")
    claimed, _definition, run = _materialize_minimum_size_candidate(
        repository,
        "minimum-size-global-budget-v7",
    )
    assert claimed.cycle_number == 1
    plan = repository.get_spot_single_child_plan(
        run.definition_id,
        run.definition_revision,
    )
    assert plan is not None

    for cycle_number in range(2, 11):
        _, cycle = _allocate_spot_eligibility_cycle(
            repository,
            run.run_id,
            plan.plan_sha256,
            f"minimum-size-global-budget-{cycle_number}",
        )
        assert cycle.cycle_number == cycle_number
        category = AUTOMATION_SPOT_ELIGIBILITY_CATEGORIES[0]
        repository.start_spot_eligibility_attempt(
            run.run_id,
            category=category,
            command=_mutation(f"minimum-size-budget-{cycle_number}-start"),
        )
        repository.finalize_spot_eligibility_attempt(
            run.run_id,
            category=category,
            outcome="REJECTED",
            eligible=False,
            coinbase_api_call_count=1,
            call_count_exact=True,
            portfolio_id_sha256=None,
            **_eligibility_evidence(
                f"minimum-size-budget-{cycle_number}",
                "REJECTED",
            ),
            command=_mutation(f"minimum-size-budget-{cycle_number}-finish"),
        )

    with pytest.raises(AutomationStoreConflict) as exhausted:
        _allocate_spot_eligibility_cycle(
            repository,
            run.run_id,
            plan.plan_sha256,
            "minimum-size-global-budget-eleventh",
        )
    assert exhausted.value.code == "automation_spot_eligibility_cycles_exhausted"


def test_near_market_service_materializes_the_exact_hashed_runner_plan(
    repository_harness: _Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = repository_harness.repository()
    _seal_rejected_v3_predecessor(repository, "near-market-service")
    portfolio_id = "11111111-1111-4111-8111-111111111111"
    monkeypatch.setenv("COINBASE_ADMIN_API_SPOT_PORTFOLIO_ID", portfolio_id)
    plan = NearMarketBuyPlan(
        policy_revision=NEAR_MARKET_POLICY_REVISION,
        product_id="BTC-USDC",
        side="BUY",
        base_size="0.00001",
        limit_price="49999",
        submitted_notional_usdc="0.49999",
        possible_execution_notional_usdc="0.49999",
        max_submitted_notional_usdc="3.10",
        max_possible_execution_notional_usdc="1.00",
        post_only=True,
    )
    evidence = near_market_preparation_evidence_sha256(
        call_count=6,
        categories=AUTOMATION_SPOT_ELIGIBILITY_CATEGORIES[:6],
        diagnostic_code="automation_near_market_terms_derived",
        outcome="MATERIALIZED",
        policy_revision=NEAR_MARKET_POLICY_REVISION,
        plan={
            "base_size": plan.base_size,
            "limit_price": plan.limit_price,
            "max_possible_execution_notional_usdc": (
                plan.max_possible_execution_notional_usdc
            ),
            "max_submitted_notional_usdc": plan.max_submitted_notional_usdc,
            "possible_execution_notional_usdc": (
                plan.possible_execution_notional_usdc
            ),
            "post_only": plan.post_only,
            "portfolio_id_sha256": hashlib.sha256(
                portfolio_id.encode("utf-8")
            ).hexdigest(),
            "product_id": plan.product_id,
            "side": plan.side,
            "submitted_notional_usdc": plan.submitted_notional_usdc,
        },
    )
    result = NearMarketPreparationResult(
        outcome=NearMarketPreparationOutcome.MATERIALIZED,
        diagnostic_code="automation_near_market_terms_derived",
        completed_categories=tuple(AUTOMATION_SPOT_ELIGIBILITY_CATEGORIES[:6]),
        coinbase_api_call_count=6,
        call_count_exact=True,
        evidence_sha256=evidence,
        plan=plan,
    )
    adapter = PostgresOperatorAutomationRepositoryAdapter(
        repository,
        spot_near_market_preparation_runner=lambda: result,
    )

    mutation = adapter.prepare_near_market_candidate(
        request={
            "confirm_backend_derived_terms": True,
            "confirm_one_no_retry_preparation_cycle": True,
            "confirm_btc_usdc_test_portfolio_scope": True,
            "confirm_unknown_consumes_cycle": True,
            "reason": "Prepare exact backend-derived terms",
        },
        context=AutomationMutationContext(
            actor_id="operator-near-market",
            roles=("operator",),
            idempotency_key="k" * 255,
            correlation_id="near-market-service-correlation",
            operator_intent="prepare_automation_near_market_candidate",
        ),
    )

    assert mutation.entity["outcome"] == "MATERIALIZED"
    assert mutation.entity["diagnostic_code"] == (
        "automation_near_market_terms_derived"
    )
    stored = repository.list_spot_near_market_preparations()
    assert stored[-1].state == "MATERIALIZED"
    assert stored[-1].evidence_sha256 == evidence


def test_minimum_size_service_materializes_exact_dynamic_cap_plan(
    repository_harness: _Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = repository_harness.repository()
    _seal_rejected_v3_predecessor(repository, "minimum-size-service")
    v4 = repository.start_spot_near_market_preparation(
        _mutation("minimum-size-service-v4")
    ).entity
    v4_evidence = near_market_preparation_evidence_sha256(
        call_count=6,
        categories=AUTOMATION_SPOT_ELIGIBILITY_CATEGORIES[:6],
        diagnostic_code="near_market_no_valid_size",
        outcome="BLOCKED",
        policy_revision=NEAR_MARKET_POLICY_REVISION,
        plan=None,
    )
    repository.finalize_spot_near_market_preparation(
        cycle_number=v4.cycle_number,
        goal_key=v4.goal_key,
        state="BLOCKED",
        diagnostic_code="near_market_no_valid_size",
        completed_categories=tuple(AUTOMATION_SPOT_ELIGIBILITY_CATEGORIES[:6]),
        coinbase_api_call_count=6,
        call_count_exact=True,
        evidence_sha256=v4_evidence,
        definition_id=None,
    )
    portfolio_id = "11111111-1111-4111-8111-111111111111"
    monkeypatch.setenv("COINBASE_ADMIN_API_SPOT_PORTFOLIO_ID", portfolio_id)
    plan = MinimumSizeBuyPlan(
        policy_revision=MINIMUM_SIZE_POLICY_REVISION,
        product_id="BTC-USDC",
        side="BUY",
        base_size="0.00001",
        limit_price="100000",
        submitted_notional_usdc="1",
        possible_execution_notional_usdc="1",
        max_submitted_notional_usdc="3.10",
        max_possible_execution_notional_usdc="1.01",
        post_only=True,
        v4_boundary_classification=(
            "minimum_size_v4_fee_reserve_conflict"
        ),
    )
    evidence = minimum_size_preparation_evidence_sha256(
        call_count=6,
        categories=AUTOMATION_SPOT_ELIGIBILITY_CATEGORIES[:6],
        diagnostic_code=plan.v4_boundary_classification,
        outcome="MATERIALIZED",
        policy_revision=MINIMUM_SIZE_POLICY_REVISION,
        plan={
            "base_size": plan.base_size,
            "limit_price": plan.limit_price,
            "max_possible_execution_notional_usdc": (
                plan.max_possible_execution_notional_usdc
            ),
            "max_submitted_notional_usdc": plan.max_submitted_notional_usdc,
            "possible_execution_notional_usdc": (
                plan.possible_execution_notional_usdc
            ),
            "post_only": plan.post_only,
            "portfolio_id_sha256": hashlib.sha256(
                portfolio_id.encode("utf-8")
            ).hexdigest(),
            "product_id": plan.product_id,
            "side": plan.side,
            "submitted_notional_usdc": plan.submitted_notional_usdc,
            "v4_boundary_classification": plan.v4_boundary_classification,
        },
    )
    adapter = PostgresOperatorAutomationRepositoryAdapter(
        repository,
        spot_minimum_size_preparation_runner=lambda: (
            MinimumSizePreparationResult(
                outcome=MinimumSizePreparationOutcome.MATERIALIZED,
                diagnostic_code=plan.v4_boundary_classification,
                completed_categories=tuple(
                    AUTOMATION_SPOT_ELIGIBILITY_CATEGORIES[:6]
                ),
                coinbase_api_call_count=6,
                call_count_exact=True,
                evidence_sha256=evidence,
                plan=plan,
            )
        ),
    )

    original_create_definition = repository.create_definition
    materialization_attempts = 0

    def fail_first_materialization(*args, **kwargs):
        nonlocal materialization_attempts
        materialization_attempts += 1
        if materialization_attempts == 1:
            raise RuntimeError("withheld-materialization-failure")
        return original_create_definition(*args, **kwargs)

    monkeypatch.setattr(
        repository,
        "create_definition",
        fail_first_materialization,
    )

    unknown = adapter.prepare_minimum_size_candidate(
        request={
            "confirm_backend_derived_terms": True,
            "confirm_one_no_retry_preparation_cycle": True,
            "confirm_btc_usdc_test_portfolio_scope": True,
            "confirm_dynamic_cap_strictly_below_3_10": True,
            "confirm_unknown_consumes_cycle": True,
            "reason": "Exercise conservative materialization failure",
        },
        context=AutomationMutationContext(
            actor_id="operator-minimum-size",
            roles=("operator",),
            idempotency_key="minimum-size-materialization-failure",
            correlation_id="minimum-size-materialization-failure",
            operator_intent="prepare_automation_minimum_size_candidate",
        ),
    )

    assert unknown.entity["outcome"] == "UNKNOWN"
    assert unknown.entity["diagnostic_code"] == (
        "automation_minimum_size_preparation_unknown"
    )
    assert unknown.entity["call_count_exact"] is False
    assert unknown.entity["definition"] is None

    mutation = adapter.prepare_minimum_size_candidate(
        request={
            "confirm_backend_derived_terms": True,
            "confirm_one_no_retry_preparation_cycle": True,
            "confirm_btc_usdc_test_portfolio_scope": True,
            "confirm_dynamic_cap_strictly_below_3_10": True,
            "confirm_unknown_consumes_cycle": True,
            "reason": "Prepare exact minimum-size successor",
        },
        context=AutomationMutationContext(
            actor_id="operator-minimum-size",
            roles=("operator",),
            idempotency_key="m" * 255,
            correlation_id="minimum-size-service-correlation",
            operator_intent="prepare_automation_minimum_size_candidate",
        ),
    )

    assert mutation.entity["outcome"] == "MATERIALIZED"
    assert mutation.entity["max_possible_execution_notional_usdc"] == "1.01"
    assert mutation.entity["boundary_classification"] == (
        "minimum_size_v4_fee_reserve_conflict"
    )
    readback = mutation.entity["definition"]["minimum_size_preparation"]
    assert readback == {
        "policy_revision": "BTC_USDC_POST_ONLY_BEST_BID_MINIMUM_SIZE_V2",
        "boundary_classification": "minimum_size_v4_fee_reserve_conflict",
        "cycle_number": 2,
        "completed_categories": [
            "api_key_permissions",
            "portfolio_catalog",
            "wallet_balances",
            "product_metadata",
            "best_bid_ask",
            "fee_summary",
        ],
        "coinbase_api_call_count": 6,
        "call_count_exact": True,
        "max_submitted_notional_usdc": "3.10",
        "max_possible_execution_notional_usdc": "1.01",
    }


def test_near_market_preparation_restart_consumes_unknown_cycle_without_candidate(
    repository_harness: _Harness,
) -> None:
    repository = repository_harness.repository()
    _seal_rejected_v3_predecessor(repository, "near-market-restart")
    claimed = repository.start_spot_near_market_preparation(
        _mutation("near-market-restart-v4-preparation")
    ).entity

    restarted = repository_harness.repository()
    restarted.recover_runs_after_restart()

    recovered = restarted.list_spot_near_market_preparations()
    assert len(recovered) == 1
    assert recovered[0].cycle_number == claimed.cycle_number
    assert recovered[0].state == "UNKNOWN"
    assert recovered[0].definition_id is None
    assert recovered[0].coinbase_api_call_count is None
    assert recovered[0].call_count_exact is False
    assert recovered[0].evidence_sha256 is None
    next_claim = restarted.start_spot_near_market_preparation(
        _mutation("near-market-restart-v4-preparation-next")
    ).entity
    assert next_claim.goal_key == AUTOMATION_SPOT_NEAR_MARKET_V4_GOAL_KEY
    assert next_claim.cycle_number == claimed.cycle_number + 1


def test_near_market_v4_v6_sequence_has_distinct_single_use_allowances(
    repository_harness: _Harness,
) -> None:
    repository = repository_harness.repository()
    _seal_rejected_v3_predecessor(repository, "near-market-sequence")
    expected = (
        (4, AUTOMATION_SPOT_NEAR_MARKET_V4_GOAL_KEY),
        (5, AUTOMATION_SPOT_NEAR_MARKET_V5_GOAL_KEY),
        (6, AUTOMATION_SPOT_NEAR_MARKET_V6_GOAL_KEY),
    )
    runs = []
    for version, goal_key in expected:
        claimed, _definition, run = _materialize_near_market_candidate(
            repository,
            f"near-market-sequence-v{version}",
        )
        assert claimed.candidate_version == version
        assert claimed.goal_key == goal_key
        _complete_eligible_cycle(
            repository,
            run.run_id,
            f"near-market-sequence-v{version}-eligibility",
        )
        cycle = repository.list_spot_eligibility_cycles(
            goal_key=goal_key,
        )[-1]
        repository.start_spot_preview_invocation(
            run.run_id,
            eligibility_cycle=cycle.cycle_number,
            command=_mutation(f"near-market-sequence-v{version}-preview-start"),
        )
        outcome = (
            "REJECTED" if version == 4 else "UNKNOWN" if version == 5 else "ACCEPTED"
        )
        failure_class = {
            "REJECTED": "DOCUMENTED_REJECTION",
            "UNKNOWN": "TRANSPORT_UNKNOWN",
            "ACCEPTED": "NONE",
        }[outcome]
        repository.finalize_spot_preview_invocation(
            run.run_id,
            outcome=outcome,
            failure_class=failure_class,
            rejection_code=("LIMIT_PRICE" if outcome == "REJECTED" else None),
            warning_present=False,
            preview_id_sha256=("a" * 64 if outcome == "ACCEPTED" else None),
            preview_call_count=(None if outcome == "UNKNOWN" else 1),
            call_count_exact=outcome != "UNKNOWN",
            command=_mutation(f"near-market-sequence-v{version}-preview-finish"),
        )
        goal = repository.get_spot_preview_gated_goal(goal_key=goal_key)
        assert goal.preview_allowance_consumed is True
        assert goal.preview_outcome == outcome
        assert goal.create_allowance_consumed is False
        runs.append(run)

    accepted_run = runs[-1]
    accepted_cycle = repository.list_spot_eligibility_cycles(
        goal_key=AUTOMATION_SPOT_NEAR_MARKET_V6_GOAL_KEY,
    )[-1]
    started = repository.start_spot_create_invocation(
        accepted_run.run_id,
        eligibility_cycle=accepted_cycle.cycle_number,
        command=_mutation("near-market-sequence-v6-create-start"),
    ).entity
    repository.finalize_spot_create_invocation(
        accepted_run.run_id,
        outcome="ACCEPTED",
        child_terminal=False,
        coinbase_api_call_count=1,
        call_count_exact=True,
        read_call_count=1,
        read_call_count_exact=True,
        command=_mutation("near-market-sequence-v6-create-finish"),
    )
    repository.start_spot_cancel_invocation(
        accepted_run.run_id,
        client_order_id=started.client_order_id,
        command=_mutation("near-market-sequence-v6-cancel-start"),
    )
    repository.finalize_spot_cancel_invocation(
        accepted_run.run_id,
        outcome="ACCEPTED",
        child_terminal=True,
        coinbase_api_call_count=1,
        call_count_exact=True,
        read_call_count=2,
        read_call_count_exact=True,
        command=_mutation("near-market-sequence-v6-cancel-finish"),
    )
    v6_goal = repository.get_spot_preview_gated_goal(
        goal_key=AUTOMATION_SPOT_NEAR_MARKET_V6_GOAL_KEY,
    )
    assert v6_goal.create_allowance_consumed is True
    assert v6_goal.create_outcome == "ACCEPTED"
    assert v6_goal.cancel_allowance_consumed is True
    assert v6_goal.cancel_outcome == "ACCEPTED"
    with pytest.raises(AutomationStoreConflict) as exhausted:
        repository.start_spot_near_market_preparation(
            _mutation("near-market-sequence-v7-forbidden")
        )
    assert exhausted.value.code == "automation_near_market_successor_not_available"


def test_near_market_preparation_and_eligibility_share_ten_cycle_budget(
    repository_harness: _Harness,
) -> None:
    repository = repository_harness.repository()
    _seal_rejected_v3_predecessor(repository, "near-market-global-budget")
    claimed, _definition, run = _materialize_near_market_candidate(
        repository,
        "near-market-global-budget-v4",
    )
    assert claimed.cycle_number == 1
    plan = repository.get_spot_single_child_plan(
        run.definition_id,
        run.definition_revision,
    )
    assert plan is not None

    for cycle_number in range(2, 11):
        _, cycle = _allocate_spot_eligibility_cycle(
            repository,
            run.run_id,
            plan.plan_sha256,
            f"near-market-global-budget-cycle-{cycle_number}",
        )
        assert cycle.cycle_number == cycle_number
        category = AUTOMATION_SPOT_ELIGIBILITY_CATEGORIES[0]
        repository.start_spot_eligibility_attempt(
            run.run_id,
            category=category,
            command=_mutation(
                f"near-market-global-budget-{cycle_number}-start"
            ),
        )
        repository.finalize_spot_eligibility_attempt(
            run.run_id,
            category=category,
            outcome="REJECTED",
            eligible=False,
            coinbase_api_call_count=1,
            call_count_exact=True,
            portfolio_id_sha256=None,
            **_eligibility_evidence(
                f"near-market-global-budget-{cycle_number}",
                "REJECTED",
            ),
            command=_mutation(
                f"near-market-global-budget-{cycle_number}-finish"
            ),
        )

    with pytest.raises(AutomationStoreConflict) as exhausted:
        _allocate_spot_eligibility_cycle(
            repository,
            run.run_id,
            plan.plan_sha256,
            "near-market-global-budget-eleventh",
        )
    assert exhausted.value.code == "automation_spot_eligibility_cycles_exhausted"


def test_preview_claim_is_single_use_and_rejection_leaves_create_unconsumed(
    repository_harness: _Harness,
):
    repository = repository_harness.repository()
    _seal_rejected_predecessor(repository, "preview-claim-predecessor")
    definition = repository.create_definition(
        _definition_command(
            "preview-claim-successor",
            product_ids=("BTC-USDC",),
        ),
        spot_single_child_plan=_spot_plan_terms(),
        spot_goal_key=AUTOMATION_SPOT_PREVIEW_GATED_GOAL_KEY,
    ).entity
    enabled = repository.transition_definition(
        definition.definition_id,
        "enable",
        _mutation("preview-claim-enable"),
    ).entity
    run = repository.claim_one_shot_run(
        enabled.definition_id,
        _mutation("preview-claim-run"),
    ).entity
    repository.transition_run(
        run.run_id,
        OperatorAutomationRunState.PREPARING,
        diagnostic_code="preparing",
        command=_mutation("preview-claim-preparing"),
    )
    _complete_eligible_cycle(repository, run.run_id, "preview-claim-cycle")
    cycle = repository.list_spot_eligibility_cycles(
        goal_key=AUTOMATION_SPOT_PREVIEW_GATED_GOAL_KEY
    )[0]

    started = repository.start_spot_preview_invocation(
        run.run_id,
        eligibility_cycle=cycle.cycle_number,
        command=_mutation("preview-claim-start"),
    )
    assert started.entity.preview_allowance_consumed is True
    assert started.entity.preview_outcome is None
    assert repository.get_spot_run_execution(run.run_id) is None
    with pytest.raises(AutomationStoreConflict) as duplicate:
        repository.start_spot_preview_invocation(
            run.run_id,
            eligibility_cycle=cycle.cycle_number,
            command=_mutation("preview-claim-second"),
        )
    assert duplicate.value.code == "automation_spot_preview_allowance_consumed"

    finalized = repository.finalize_spot_preview_invocation(
        run.run_id,
        outcome="REJECTED",
        failure_class="DOCUMENTED_REJECTION",
        rejection_code="INSUFFICIENT_FUNDS",
        warning_present=False,
        preview_id_sha256=None,
        preview_call_count=1,
        call_count_exact=True,
        command=_mutation("preview-claim-finish"),
    )
    assert finalized.entity.preview_outcome == "REJECTED"
    assert finalized.entity.preview_failure_class == "DOCUMENTED_REJECTION"
    assert finalized.entity.preview_rejection_code == "INSUFFICIENT_FUNDS"
    assert finalized.entity.create_allowance_consumed is False
    assert finalized.entity.bound_run_id == run.run_id
    terminal = repository.get_run(run.run_id)
    assert terminal is not None
    assert terminal.state is OperatorAutomationRunState.TERMINAL
    assert terminal.diagnostic_code == "automation_spot_preview_rejected"
    assert terminal.create_call_count == 0


def test_preview_rejection_code_rejects_unallowlisted_values(
    repository_harness: _Harness,
):
    repository = repository_harness.repository()
    _seal_rejected_predecessor(repository, "preview-code-predecessor")
    definition = repository.create_definition(
        _definition_command("preview-code-successor", product_ids=("BTC-USDC",)),
        spot_single_child_plan=_spot_plan_terms(),
        spot_goal_key=AUTOMATION_SPOT_PREVIEW_GATED_GOAL_KEY,
    ).entity
    enabled = repository.transition_definition(
        definition.definition_id,
        "enable",
        _mutation("preview-code-enable"),
    ).entity
    run = repository.claim_one_shot_run(
        enabled.definition_id,
        _mutation("preview-code-run"),
    ).entity
    repository.transition_run(
        run.run_id,
        OperatorAutomationRunState.PREPARING,
        diagnostic_code="preparing",
        command=_mutation("preview-code-preparing"),
    )
    _complete_eligible_cycle(repository, run.run_id, "preview-code-cycle")
    repository.start_spot_preview_invocation(
        run.run_id,
        eligibility_cycle=1,
        command=_mutation("preview-code-start"),
    )

    with pytest.raises(AutomationStoreInvalid) as error:
        repository.finalize_spot_preview_invocation(
            run.run_id,
            outcome="REJECTED",
            failure_class="DOCUMENTED_REJECTION",
            rejection_code="PRIVATE_RAW_REASON",
            warning_present=False,
            preview_id_sha256=None,
            preview_call_count=1,
            call_count_exact=True,
            command=_mutation("preview-code-finish"),
        )

    assert error.value.code == "automation_spot_preview_result_invalid"


def test_accepted_preview_unlocks_only_v2_create_allowance(
    repository_harness: _Harness,
):
    repository = repository_harness.repository()
    _seal_rejected_predecessor(repository, "preview-create-predecessor")
    predecessor_goal = repository.get_spot_live_proof_goal()
    definition = repository.create_definition(
        _definition_command(
            "preview-create-successor",
            product_ids=("BTC-USDC",),
        ),
        spot_single_child_plan=_spot_plan_terms(),
        spot_goal_key=AUTOMATION_SPOT_PREVIEW_GATED_GOAL_KEY,
    ).entity
    enabled = repository.transition_definition(
        definition.definition_id,
        "enable",
        _mutation("preview-create-enable"),
    ).entity
    run = repository.claim_one_shot_run(
        enabled.definition_id,
        _mutation("preview-create-run"),
    ).entity
    repository.transition_run(
        run.run_id,
        OperatorAutomationRunState.PREPARING,
        diagnostic_code="preparing",
        command=_mutation("preview-create-preparing"),
    )
    _complete_eligible_cycle(repository, run.run_id, "preview-create-cycle")
    repository.start_spot_preview_invocation(
        run.run_id,
        eligibility_cycle=1,
        command=_mutation("preview-create-preview-start"),
    )
    repository.finalize_spot_preview_invocation(
        run.run_id,
        outcome="ACCEPTED",
        failure_class="NONE",
        rejection_code=None,
        warning_present=True,
        preview_id_sha256="a" * 64,
        preview_call_count=1,
        call_count_exact=True,
        command=_mutation("preview-create-preview-finish"),
    )

    started = repository.start_spot_create_invocation(
        run.run_id,
        eligibility_cycle=1,
        command=_mutation("preview-create-start"),
    )
    assert started.entity.create_allowance_consumed is True
    assert repository.get_spot_live_proof_goal() == predecessor_goal
    successor_goal = repository.get_spot_preview_gated_goal()
    assert successor_goal.preview_outcome == "ACCEPTED"
    assert successor_goal.create_allowance_consumed is True
    assert successor_goal.create_outcome is None

    repository.finalize_spot_create_invocation(
        run.run_id,
        outcome="ACCEPTED",
        child_terminal=False,
        coinbase_api_call_count=1,
        call_count_exact=True,
        read_call_count=1,
        read_call_count_exact=True,
        command=_mutation("preview-create-finish"),
    )
    active_goal = repository.get_spot_preview_gated_goal()
    assert active_goal.create_outcome == "ACCEPTED"
    assert active_goal.cancel_allowance_consumed is False
    active_run = repository.get_run(run.run_id)
    assert active_run is not None
    assert active_run.state is OperatorAutomationRunState.ACTIVE

    repository.start_spot_cancel_invocation(
        run.run_id,
        client_order_id=started.entity.client_order_id,
        command=_mutation("preview-create-cancel-start"),
    )
    repository.finalize_spot_cancel_invocation(
        run.run_id,
        outcome="ACCEPTED",
        child_terminal=True,
        coinbase_api_call_count=1,
        call_count_exact=True,
        read_call_count=2,
        read_call_count_exact=True,
        command=_mutation("preview-create-cancel-finish"),
    )
    terminal_goal = repository.get_spot_preview_gated_goal()
    assert terminal_goal.cancel_allowance_consumed is True
    assert terminal_goal.cancel_outcome == "ACCEPTED"
    terminal_run = repository.get_run(run.run_id)
    assert terminal_run is not None
    assert terminal_run.state is OperatorAutomationRunState.TERMINAL
    assert terminal_run.coinbase_api_call_count == 6
    assert terminal_run.create_call_count == 1
    assert terminal_run.cancel_call_count == 1


def test_preview_claim_restart_is_unknown_consumed_without_create(
    repository_harness: _Harness,
):
    repository = repository_harness.repository()
    _seal_rejected_predecessor(repository, "preview-restart-predecessor")
    definition = repository.create_definition(
        _definition_command(
            "preview-restart-successor",
            product_ids=("BTC-USDC",),
        ),
        spot_single_child_plan=_spot_plan_terms(),
        spot_goal_key=AUTOMATION_SPOT_PREVIEW_GATED_GOAL_KEY,
    ).entity
    enabled = repository.transition_definition(
        definition.definition_id,
        "enable",
        _mutation("preview-restart-enable"),
    ).entity
    run = repository.claim_one_shot_run(
        enabled.definition_id,
        _mutation("preview-restart-run"),
    ).entity
    repository.transition_run(
        run.run_id,
        OperatorAutomationRunState.PREPARING,
        diagnostic_code="preparing",
        command=_mutation("preview-restart-preparing"),
    )
    _complete_eligible_cycle(repository, run.run_id, "preview-restart-cycle")
    repository.start_spot_preview_invocation(
        run.run_id,
        eligibility_cycle=1,
        command=_mutation("preview-restart-start"),
    )

    restarted = repository_harness.repository()
    recovered = restarted.recover_runs_after_restart()

    assert [item.run_id for item in recovered] == [run.run_id]
    assert recovered[0].state is OperatorAutomationRunState.UNKNOWN_CONSUMED
    assert recovered[0].diagnostic_code == (
        "automation_spot_preview_unknown_consumed"
    )
    goal = restarted.get_spot_preview_gated_goal()
    assert goal.preview_allowance_consumed is True
    assert goal.preview_outcome == "UNKNOWN"
    assert goal.preview_failure_class == "TRANSPORT_UNKNOWN"
    assert goal.preview_call_count is None
    assert goal.preview_call_count_exact is False
    assert goal.create_allowance_consumed is False
    assert restarted.recover_runs_after_restart() == ()
