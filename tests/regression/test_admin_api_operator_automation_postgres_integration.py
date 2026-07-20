"""Production route/service/adapter integration against isolated test PostgreSQL."""

from __future__ import annotations

import hashlib
import os
import re
import uuid

from fastapi.testclient import TestClient
from psycopg2 import sql
import pytest

from api.v1.app import create_app
from api.v1.routes import operator_automation as operator_automation_routes
from application.admin_api.operator_automation import (
    OperatorAutomationService,
    PostgresOperatorAutomationRepositoryAdapter,
)
from application.admin_api.automation_models import AutomationMutationContext
from core.enums import OperatorAutomationRunState
from database.database import PostgresDB
from database.operator_automation import (
    AutomationMutationCommand,
    OperatorAutomationRepository,
)


pytestmark = [pytest.mark.regression, pytest.mark.serial]

TEST_DB_HOST = os.environ.get("COINBASE_DB_HOST", "coinbase-test-postgres")
TEST_DB_PORT = int(os.environ.get("COINBASE_DB_PORT", "9876"))
TEST_DB_NAME = os.environ.get("COINBASE_DB_NAME", "postgres")
TEST_DB_USER = os.environ.get("COINBASE_DB_USER", "postgres")
TEST_DB_PASSWORD = os.environ.get("COINBASE_DB_PASSWORD", "postgres")
_SCHEMA_PATTERN = re.compile(r"^test_admin_automation_[0-9a-f]{32}$")


def _database() -> PostgresDB:
    assert TEST_DB_HOST == "coinbase-test-postgres"
    assert TEST_DB_PORT == 9876
    return PostgresDB(
        host=TEST_DB_HOST,
        port=TEST_DB_PORT,
        database=TEST_DB_NAME,
        user=TEST_DB_USER,
        password=TEST_DB_PASSWORD,
    )


def _headers(*, key: str, intent: str) -> dict[str, str]:
    return {
        "Authorization": "Bearer local-automation-integration-token",
        "X-Admin-Actor": "operator-automation-integration",
        "X-Admin-Roles": "trader",
        "Idempotency-Key": key,
        "X-Correlation-Id": f"correlation-{key}",
        "X-Operator-Intent": intent,
    }


def test_real_postgres_route_workflow_is_durable_blocked_and_replay_safe(
    monkeypatch: pytest.MonkeyPatch,
):
    schema = f"test_admin_automation_{uuid.uuid4().hex}"
    assert _SCHEMA_PATTERN.fullmatch(schema)
    database = _database()
    repository = OperatorAutomationRepository(database, schema=schema)
    repository.ensure_schema()
    adapter = PostgresOperatorAutomationRepositoryAdapter(repository)
    service = OperatorAutomationService(adapter)
    monkeypatch.setenv("COINBASE_ADMIN_API_AUTH_MODE", "bootstrap_bearer")
    monkeypatch.setenv(
        "COINBASE_ADMIN_API_BEARER_TOKEN",
        "local-automation-integration-token",
    )
    monkeypatch.setenv(
        "COINBASE_ADMIN_API_OPERATOR_AUTOMATION_ENABLED",
        "1",
    )
    app = create_app()
    app.dependency_overrides[
        operator_automation_routes.get_operator_automation_service
    ] = lambda: service

    try:
        with TestClient(app) as client:
            created = client.post(
                "/api/v1/automation/definitions",
                json={
                    "display_name": "Integrated Spot sweep review",
                    "job_kind": "SPOT_SWEEP",
                    "product_ids": ["BTC-USDC"],
                },
                headers=_headers(
                    key="integration-definition-create",
                    intent="create_automation_definition",
                ),
            )
            assert created.status_code == 200
            definition_id = created.json()["definition"]["definition_id"]

            enabled = client.post(
                f"/api/v1/automation/definitions/{definition_id}/enable",
                json={"reason": "Enable one bounded readiness review"},
                headers=_headers(
                    key="integration-definition-enable",
                    intent="enable_automation_definition",
                ),
            )
            assert enabled.status_code == 200
            assert enabled.json()["definition"]["lifecycle_state"] == "ENABLED"

            claim_body = {
                "confirm_one_shot": True,
                "reason": "One explicit adapter readiness review",
            }
            claim_headers = _headers(
                key="integration-run-claim",
                intent="claim_automation_one_shot_run",
            )
            claimed = client.post(
                f"/api/v1/automation/definitions/{definition_id}/runs",
                json=claim_body,
                headers=claim_headers,
            )
            assert claimed.status_code == 200
            run = claimed.json()["run"]
            assert run["state"] == "BLOCKED"
            assert run["diagnostic_code"] == (
                "automation_domain_adapter_unavailable"
            )
            assert run["coinbase_api_call_count"] == 0
            assert run["create_call_count"] == 0
            assert run["cancel_call_count"] == 0

            replay = client.post(
                f"/api/v1/automation/definitions/{definition_id}/runs",
                json=claim_body,
                headers=claim_headers,
            )
            assert replay.status_code == 200
            assert replay.headers["X-Idempotency-Replayed"] == "true"
            assert replay.json()["run"] == run

            events = client.get(
                f"/api/v1/automation/runs/{run['run_id']}/events",
                headers={
                    "Authorization": "Bearer local-automation-integration-token",
                    "X-Admin-Actor": "operator-automation-integration",
                    "X-Admin-Roles": "trader",
                },
            )
            assert events.status_code == 200
            assert [item["state"] for item in events.json()["items"]] == [
                "CLAIMED",
                "BLOCKED",
            ]
            assert events.json()["pagination"]["total_matching_count"] == 2
            assert all(item["audit_id"] for item in events.json()["items"])
            assert all(item["correlation_id"] for item in events.json()["items"])

            interrupted_created = client.post(
                "/api/v1/automation/definitions",
                json={
                    "display_name": "Interrupted Spot sweep review",
                    "job_kind": "SPOT_SWEEP",
                    "product_ids": ["BTC-USDC"],
                },
                headers=_headers(
                    key="integration-interrupted-definition-create",
                    intent="create_automation_definition",
                ),
            )
            assert interrupted_created.status_code == 200
            interrupted_definition_id = interrupted_created.json()["definition"][
                "definition_id"
            ]
            interrupted_enabled = client.post(
                f"/api/v1/automation/definitions/{interrupted_definition_id}/enable",
                json={"reason": "Enable interrupted restart replay proof"},
                headers=_headers(
                    key="integration-interrupted-definition-enable",
                    intent="enable_automation_definition",
                ),
            )
            assert interrupted_enabled.status_code == 200

            interrupted_body = {
                "confirm_one_shot": True,
                "reason": "Recover an interrupted one-shot claim",
            }
            interrupted_key = "integration-interrupted-run-claim"
            interrupted_context = AutomationMutationContext(
                actor_id="operator-automation-integration",
                roles=("trader",),
                idempotency_key=interrupted_key,
                correlation_id=f"correlation-{interrupted_key}",
                operator_intent="claim_automation_one_shot_run",
            )
            interrupted_command = adapter._command(
                context=interrupted_context,
                payload={
                    "operation": "claim_one_shot_run",
                    "definition_id": interrupted_definition_id,
                    "request": interrupted_body,
                },
            )
            interrupted_run = repository.claim_one_shot_run(
                interrupted_definition_id,
                interrupted_command,
            ).entity

            def transition_command(seed: str) -> AutomationMutationCommand:
                return AutomationMutationCommand(
                    idempotency_key=f"private-{seed}",
                    payload_sha256=hashlib.sha256(seed.encode("utf-8")).hexdigest(),
                    actor_id="operator-automation-integration",
                    correlation_id=f"correlation-{seed}",
                    operator_intent=f"advance_{seed}",
                )

            for state, diagnostic, seed in (
                (OperatorAutomationRunState.PREPARING, "preparing", "preparing"),
                (
                    OperatorAutomationRunState.AWAITING_OPERATOR_AUTHORIZATION,
                    "awaiting_operator_authorization",
                    "awaiting",
                ),
                (
                    OperatorAutomationRunState.INVOCATION_STARTED,
                    "invocation_started",
                    "invoked",
                ),
                (OperatorAutomationRunState.ACTIVE, "active", "active"),
            ):
                repository.transition_run(
                    interrupted_run.run_id,
                    state,
                    diagnostic_code=diagnostic,
                    command=transition_command(seed),
                )
            recovered = repository.recover_runs_after_restart()
            assert recovered[-1].state is OperatorAutomationRunState.UNKNOWN_CONSUMED

            interrupted_replay = client.post(
                f"/api/v1/automation/definitions/{interrupted_definition_id}/runs",
                json=interrupted_body,
                headers=_headers(
                    key=interrupted_key,
                    intent="claim_automation_one_shot_run",
                ),
            )
            assert interrupted_replay.status_code == 200
            assert interrupted_replay.headers["X-Idempotency-Replayed"] == "true"
            assert interrupted_replay.json()["run"]["state"] == "UNKNOWN_CONSUMED"
            assert interrupted_replay.json()["run"]["diagnostic_code"] == (
                "restart_unknown_consumed"
            )
            interrupted_events = client.get(
                f"/api/v1/automation/runs/{interrupted_run.run_id}/events",
                headers={
                    "Authorization": "Bearer local-automation-integration-token",
                    "X-Admin-Actor": "operator-automation-integration",
                    "X-Admin-Roles": "trader",
                },
            )
            assert interrupted_events.status_code == 200
            assert [item["diagnostic_code"] for item in interrupted_events.json()["items"]] == [
                "one_shot_run_claimed",
                "preparing",
                "awaiting_operator_authorization",
                "invocation_started",
                "active",
                "restart_unknown_consumed",
            ]

            definition_events = client.get(
                f"/api/v1/automation/definitions/{definition_id}/events",
                headers={
                    "Authorization": "Bearer local-automation-integration-token",
                    "X-Admin-Actor": "operator-automation-integration",
                    "X-Admin-Roles": "trader",
                },
            )
            assert definition_events.status_code == 200
            assert [
                item["diagnostic_code"]
                for item in definition_events.json()["items"]
            ] == [
                "automation_definition_created",
                "automation_definition_enable",
            ]

            paused = client.post(
                "/api/v1/automation/control-plane/pause",
                json={"reason": "Verify durable control audit readback"},
                headers=_headers(
                    key="integration-control-pause",
                    intent="pause_automation_control_plane",
                ),
            )
            assert paused.status_code == 200
            control_events = client.get(
                "/api/v1/automation/control-plane/events",
                headers={
                    "Authorization": "Bearer local-automation-integration-token",
                    "X-Admin-Actor": "operator-automation-integration",
                    "X-Admin-Roles": "trader",
                },
            )
            assert control_events.status_code == 200
            assert control_events.json()["items"][-1]["diagnostic_code"] == (
                "automation_control_pause"
            )
            assert repository.list_runs(
                definition_id=definition_id,
                limit=10,
                offset=0,
            ).total_count == 1
    finally:
        app.dependency_overrides.clear()
        try:
            with database.get_cursor() as cursor:
                cursor.execute(
                    sql.SQL("DROP SCHEMA {} CASCADE").format(
                        sql.Identifier(schema)
                    )
                )
        finally:
            database.disconnect()


def test_real_postgres_single_child_adapter_is_operator_visible_and_fails_before_calls(
    monkeypatch: pytest.MonkeyPatch,
):
    schema = f"test_admin_automation_{uuid.uuid4().hex}"
    assert _SCHEMA_PATTERN.fullmatch(schema)
    database = _database()
    repository = OperatorAutomationRepository(database, schema=schema)
    repository.ensure_schema()
    adapter = PostgresOperatorAutomationRepositoryAdapter(repository)
    service = OperatorAutomationService(adapter)
    monkeypatch.setenv("COINBASE_ADMIN_API_AUTH_MODE", "bootstrap_bearer")
    monkeypatch.setenv(
        "COINBASE_ADMIN_API_BEARER_TOKEN",
        "local-automation-integration-token",
    )
    monkeypatch.setenv("COINBASE_ADMIN_API_OPERATOR_AUTOMATION_ENABLED", "1")
    monkeypatch.setenv(
        "COINBASE_ADMIN_API_SPOT_PORTFOLIO_ID",
        "483d1403-5d4d-4ae1-9084-ae2b080902b7",
    )
    app = create_app()
    app.dependency_overrides[
        operator_automation_routes.get_operator_automation_service
    ] = lambda: service

    try:
        with TestClient(app) as client:
            created = client.post(
                "/api/v1/automation/definitions",
                json={
                    "display_name": "One bounded BTC child",
                    "job_kind": "SPOT_CAMPAIGN",
                    "product_ids": ["BTC-USDC"],
                    "single_child_order": {
                        "side": "BUY",
                        "base_size": "0.00001",
                        "limit_price": "50000",
                        "order_type": "LIMIT",
                        "time_in_force": "GOOD_UNTIL_CANCELLED",
                        "post_only": False,
                    },
                },
                headers=_headers(
                    key="integration-single-child-create",
                    intent="create_automation_definition",
                ),
            )
            assert created.status_code == 200, created.text
            definition = created.json()["definition"]
            assert definition["adapter_status"] == "SOURCE_GATED"
            assert definition["single_child_order"]["side"] == "BUY"

            enabled = client.post(
                f"/api/v1/automation/definitions/{definition['definition_id']}/enable",
                json={"reason": "Enable the exact one-child review"},
                headers=_headers(
                    key="integration-single-child-enable",
                    intent="enable_automation_definition",
                ),
            )
            assert enabled.status_code == 200, enabled.text

            claim_body = {
                "confirm_one_shot": True,
                "reason": "Prepare the exact one-child run",
            }
            interrupted_context = AutomationMutationContext(
                actor_id="operator-automation-integration",
                roles=("trader",),
                idempotency_key="integration-single-child-run",
                correlation_id="correlation-integration-single-child-run",
                operator_intent="claim_automation_one_shot_run",
            )
            interrupted_claim = repository.claim_one_shot_run(
                definition["definition_id"],
                adapter._command(
                    context=interrupted_context,
                    payload={
                        "operation": "claim_one_shot_run",
                        "definition_id": definition["definition_id"],
                        "request": claim_body,
                    },
                ),
            ).entity
            repository.transition_run(
                interrupted_claim.run_id,
                OperatorAutomationRunState.PREPARING,
                diagnostic_code="preparing",
                command=AutomationMutationCommand(
                    idempotency_key="integration-interrupted-preparing",
                    payload_sha256=hashlib.sha256(
                        b"integration-interrupted-preparing"
                    ).hexdigest(),
                    actor_id="operator-automation-integration",
                    correlation_id="integration-interrupted-preparing",
                    operator_intent="prepare_automation_single_child_run",
                ),
            )

            claimed = client.post(
                f"/api/v1/automation/definitions/{definition['definition_id']}/runs",
                json=claim_body,
                headers=_headers(
                    key="integration-single-child-run",
                    intent="claim_automation_one_shot_run",
                ),
            )
            assert claimed.status_code == 200, claimed.text
            assert claimed.headers["X-Idempotency-Replayed"] == "true"
            run = claimed.json()["run"]
            assert run["state"] == "BLOCKED"
            assert run["diagnostic_code"] == (
                "automation_active_order_catalog_read_not_authorized"
            )
            assert run["single_child_plan"]["product_id"] == "BTC-USDC"
            assert run["single_child_plan"]["portfolio_scope"] == (
                "CONFIGURED_UNVERIFIED"
            )
            assert run["single_child_plan"]["max_submitted_notional_usdc"] == "3.10"
            assert run["single_child_plan"][
                "max_possible_execution_notional_usdc"
            ] == "1.00"
            assert run["live_execution_available"] is False
            assert run["live_attempt_consumed"] is False
            assert run["coinbase_api_call_count"] == 0
            assert run["create_call_count"] == 0

            definition_after_claim = client.get(
                f"/api/v1/automation/definitions/{definition['definition_id']}",
                headers={
                    "Authorization": "Bearer local-automation-integration-token",
                    "X-Admin-Actor": "operator-automation-integration",
                    "X-Admin-Roles": "trader",
                },
            )
            assert definition_after_claim.status_code == 200
            assert "RUN_ONCE" not in definition_after_claim.json()[
                "definition"
            ]["allowed_actions"]

            authorization_body = {
                "confirm_single_child_create": True,
                "confirm_unknown_consumes_allowance": True,
                "expected_plan_sha256": run["single_child_plan"][
                    "plan_sha256"
                ],
                "reason": "Authorize only the exact prepared child",
            }
            authorization_headers = _headers(
                key="integration-single-child-authorize",
                intent="authorize_automation_single_child_create",
            )
            authorization = client.post(
                f"/api/v1/automation/runs/{run['run_id']}/authorize-single-child",
                json=authorization_body,
                headers=authorization_headers,
            )
            assert authorization.status_code == 409
            assert authorization.json()["message"] == (
                "automation_active_order_catalog_read_not_authorized"
            )
            exact_replay = client.post(
                f"/api/v1/automation/runs/{run['run_id']}/authorize-single-child",
                json=authorization_body,
                headers=authorization_headers,
            )
            assert exact_replay.status_code == 409
            assert exact_replay.json()["message"] == (
                "automation_active_order_catalog_read_not_authorized"
            )
            changed_correlation_headers = dict(authorization_headers)
            changed_correlation_headers["X-Correlation-Id"] = (
                "correlation-changed-under-same-idempotency-key"
            )
            changed_correlation = client.post(
                f"/api/v1/automation/runs/{run['run_id']}/authorize-single-child",
                json=authorization_body,
                headers=changed_correlation_headers,
            )
            assert changed_correlation.status_code == 409
            assert changed_correlation.json()["message"] == (
                "automation_idempotency_conflict"
            )
            changed_payload = client.post(
                f"/api/v1/automation/runs/{run['run_id']}/authorize-single-child",
                json={
                    **authorization_body,
                    "reason": "Changed request under the same key",
                },
                headers=authorization_headers,
            )
            assert changed_payload.status_code == 409
            assert changed_payload.json()["message"] == (
                "automation_idempotency_conflict"
            )
            events = client.get(
                f"/api/v1/automation/runs/{run['run_id']}/events",
                headers={
                    "Authorization": "Bearer local-automation-integration-token",
                    "X-Admin-Actor": "operator-automation-integration",
                    "X-Admin-Roles": "trader",
                },
            )
            assert events.status_code == 200, events.text
            assert [
                (
                    event["from_state"],
                    event["state"],
                    event["diagnostic_code"],
                )
                for event in events.json()["items"]
            ][-1] == (
                "BLOCKED",
                "BLOCKED",
                "automation_active_order_catalog_read_not_authorized",
            )
            assert events.json()["pagination"]["total_matching_count"] == 4
            readback = client.get(
                f"/api/v1/automation/runs/{run['run_id']}",
                headers={
                    "Authorization": "Bearer local-automation-integration-token",
                    "X-Admin-Actor": "operator-automation-integration",
                    "X-Admin-Roles": "trader",
                },
            )
            assert readback.status_code == 200
            assert readback.json()["run"]["state"] == "BLOCKED"
            assert readback.json()["run"]["coinbase_api_call_count"] == 0
            assert readback.json()["run"]["create_call_count"] == 0
            assert readback.json()["run"]["cancel_call_count"] == 0
            goal = repository.get_spot_live_proof_goal()
            assert goal.create_allowance_consumed is False
            assert goal.cancel_allowance_consumed is False
    finally:
        app.dependency_overrides.clear()
        try:
            with database.get_cursor() as cursor:
                cursor.execute(
                    sql.SQL("DROP SCHEMA {} CASCADE").format(
                        sql.Identifier(schema)
                    )
                )
        finally:
            database.disconnect()
