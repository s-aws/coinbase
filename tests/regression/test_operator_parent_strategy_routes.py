from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.v1.app import app as _APP
from api.v1.routes import operator_parent_strategy as parent_routes
from application.admin_api.operator_parent_strategy import (
    OperatorParentStrategyError,
)
from application.admin_api.operator_parent_strategy_service import (
    ParentStrategyMutationResponse,
)


pytestmark = [pytest.mark.regression, pytest.mark.serial]

STRATEGY_ID = "11111111-1111-4111-8111-111111111111"


def _strategy(
    *,
    lifecycle_state: str = "ACTIVE",
    revision: int = 1,
) -> dict[str, Any]:
    deactivated = lifecycle_state == "DEACTIVATED"
    deleted = lifecycle_state == "DELETED"
    return {
        "strategy_id": STRATEGY_ID,
        "name": "BTC follow-up parent",
        "portfolio_scope_sha256": "a" * 64,
        "admitted_product_catalog_revision_id":
            "33333333-3333-4333-8333-333333333333",
        "admitted_product_catalog_snapshot_sha256": "b" * 64,
        "product_id": "BTC-USDC",
        "side": "BUY",
        "reference_size": "0.0001",
        "reference_price": "60000",
        "target_movement": "0.005",
        "target_movement_type": "P",
        "max_order_replacement": 2,
        "allow_partial_fills": False,
        "child_order_type": "LIMIT",
        "child_time_in_force": "GOOD_UNTIL_CANCELLED",
        "child_post_only": True,
        "lifecycle_state": lifecycle_state,
        "revision": revision,
        "use_count": 0,
        "materialized_root_client_order_id": None,
        "unused_or_terminal": True,
        "active_placement_count": 0,
        "child_count": 0,
        "unresolved_claim_count": 0,
        "reconciliation_required": False,
        "delete_allowed": deactivated,
        "delete_blockers": (
            []
            if deactivated
            else ["parent_strategy_deleted"]
            if deleted
            else ["parent_strategy_not_deactivated"]
        ),
        "allowed_actions": (
            []
            if deleted
            else ["EDIT", "DELETE"]
            if deactivated
            else ["EDIT", "DEACTIVATE"]
        ),
        "created_at": "2026-07-23T00:00:00+00:00",
        "updated_at": "2026-07-23T00:00:00+00:00",
        "trading_authority_granted": False,
        "exchange_call_count": 0,
        "exchange_mutation_count": 0,
    }


@dataclass
class _Service:
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    error_code: str | None = None

    def list_strategies(self, **kwargs: Any):
        self.calls.append(("list", kwargs))
        return {
            "items": [_strategy()],
            "total_matching_count": 1,
            "limit": kwargs["limit"],
            "offset": kwargs["offset"],
            "next_offset": None,
            "lifecycle_filter": kwargs["lifecycle_state"],
            "product_filter": kwargs["product_id"],
            "commands": [],
            "command_total_count": 0,
            "command_limit": kwargs["command_limit"],
            "command_offset": kwargs["command_offset"],
            "command_next_offset": None,
            "trading_authority_granted": False,
            "exchange_call_count": 0,
            "exchange_mutation_count": 0,
        }

    def get_strategy(self, **kwargs: Any):
        self.calls.append(("get", kwargs))
        return {
            "strategy": _strategy(),
            "events": [],
            "event_total_count": 0,
            "event_limit": kwargs["event_limit"],
            "event_offset": kwargs["event_offset"],
            "event_next_offset": None,
            "trading_authority_granted": False,
            "exchange_call_count": 0,
            "exchange_mutation_count": 0,
        }

    def _mutation(self, method: str, kwargs: dict[str, Any]):
        self.calls.append((method, kwargs))
        if self.error_code:
            raise OperatorParentStrategyError(self.error_code)
        lifecycle = (
            "DEACTIVATED"
            if method == "deactivate_strategy"
            else "DELETED"
            if method == "delete_strategy"
            else "ACTIVE"
        )
        revision = (
            kwargs["body"].expected_revision + 1
            if hasattr(kwargs["body"], "expected_revision")
            else 1
        )
        return ParentStrategyMutationResponse(
            status="accepted",
            message=f"parent_strategy_{method}_accepted",
            service_method=method,
            strategy=_strategy(
                lifecycle_state=lifecycle,
                revision=revision,
            ),
            correlation_id=kwargs["correlation_id"],
            idempotency_key=kwargs["idempotency_key"],
            local_state_mutated=True,
        )

    def create_strategy(self, **kwargs: Any):
        return self._mutation("create_strategy", kwargs)

    def edit_strategy(self, **kwargs: Any):
        return self._mutation("edit_strategy", kwargs)

    def deactivate_strategy(self, **kwargs: Any):
        return self._mutation("deactivate_strategy", kwargs)

    def delete_strategy(self, **kwargs: Any):
        return self._mutation("delete_strategy", kwargs)


@pytest.fixture
def route_client(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[TestClient, _Service]:
    monkeypatch.setenv(
        "COINBASE_ADMIN_API_AUTH_MODE",
        "bootstrap_bearer",
    )
    monkeypatch.setenv(
        "COINBASE_ADMIN_API_BEARER_TOKEN",
        "local-admin-token",
    )
    monkeypatch.setenv(
        "COINBASE_ADMIN_API_OPERATOR_PARENT_STRATEGIES_ENABLED",
        "1",
    )
    service = _Service()
    _APP.dependency_overrides[
        parent_routes.get_operator_parent_strategy_service
    ] = lambda: service
    with TestClient(_APP) as client:
        yield client, service
    _APP.dependency_overrides.pop(
        parent_routes.get_operator_parent_strategy_service,
        None,
    )


def _headers(
    *,
    key: str,
    intent: str,
    roles: str = "admin,trader",
) -> dict[str, str]:
    return {
        "Authorization": "Bearer local-admin-token",
        "X-Admin-Actor": "parent-strategy-operator",
        "X-Admin-Roles": roles,
        "Idempotency-Key": key,
        "X-Correlation-Id": f"{key}-correlation",
        "X-Operator-Intent": intent,
    }


def _create_body() -> dict[str, Any]:
    return {
        "name": "BTC follow-up parent",
        "product_id": "BTC-USDC",
        "side": "BUY",
        "reference_size": "0.0001",
        "reference_price": "60000",
        "target_movement": "0.005",
        "target_movement_type": "P",
        "max_order_replacement": 2,
        "allow_partial_fills": False,
        "child_order_type": "LIMIT",
        "child_time_in_force": "GOOD_UNTIL_CANCELLED",
        "child_post_only": True,
        "operator_reason": "Create reviewed parent strategy",
        "confirm_parent_strategy_create": True,
    }


def test_parent_strategy_reads_are_authenticated_paginated_and_call_free(
    route_client: tuple[TestClient, _Service],
) -> None:
    client, service = route_client

    assert client.get("/api/v1/parent-strategies").status_code == 401
    list_response = client.get(
        "/api/v1/parent-strategies?limit=25&offset=0",
        headers=_headers(
            key="parent-read",
            intent="read_parent_strategies",
        ),
    )
    detail_response = client.get(
        f"/api/v1/parent-strategies/{STRATEGY_ID}"
        "?event_limit=25&event_offset=0",
        headers=_headers(
            key="parent-detail",
            intent="read_parent_strategy",
        ),
    )

    assert list_response.status_code == 200
    assert detail_response.status_code == 200
    assert list_response.json()["exchange_call_count"] == 0
    assert detail_response.json()["exchange_mutation_count"] == 0
    assert [name for name, _ in service.calls] == ["list", "get"]


def test_parent_strategy_create_requires_config_rbac_and_exact_intent(
    route_client: tuple[TestClient, _Service],
) -> None:
    client, service = route_client
    response = client.post(
        "/api/v1/parent-strategies",
        headers=_headers(
            key="parent-create",
            intent="create_parent_strategy",
        ),
        json=_create_body(),
    )
    viewer_response = client.post(
        "/api/v1/parent-strategies",
        headers=_headers(
            key="parent-create-viewer",
            intent="create_parent_strategy",
            roles="viewer",
        ),
        json=_create_body(),
    )
    wrong_intent = client.post(
        "/api/v1/parent-strategies",
        headers=_headers(
            key="parent-create-wrong",
            intent="delete_parent_strategy",
        ),
        json=_create_body(),
    )

    assert response.status_code == 200
    assert response.json()["strategy"]["strategy_id"] == STRATEGY_ID
    assert response.json()["exchange_call_count"] == 0
    assert viewer_response.status_code == 403
    assert wrong_intent.status_code == 422
    create_call = service.calls[0]
    assert create_call[0] == "create_strategy"
    assert set(create_call[1]) == {
        "body",
        "actor_id",
        "correlation_id",
        "idempotency_key",
    }


@pytest.mark.parametrize(
    ("suffix", "intent", "body", "method"),
    [
        (
            "edit",
            "edit_parent_strategy",
            {
                "expected_revision": 1,
                "name": "BTC follow-up parent v2",
                "target_movement": "0.006",
                "target_movement_type": "P",
                "max_order_replacement": 3,
                "allow_partial_fills": True,
                "child_order_type": "LIMIT",
                "child_time_in_force": "GOOD_UNTIL_CANCELLED",
                "child_post_only": True,
                "operator_reason": "Edit reviewed policy",
                "confirm_parent_strategy_edit": True,
            },
            "edit_strategy",
        ),
        (
            "deactivate",
            "deactivate_parent_strategy",
            {
                "expected_revision": 1,
                "operator_reason": "Stop future use",
                "confirm_parent_strategy_deactivate": True,
            },
            "deactivate_strategy",
        ),
        (
            "delete",
            "delete_parent_strategy",
            {
                "expected_revision": 2,
                "operator_reason": "Delete reviewed unused strategy",
                "confirm_parent_strategy_delete": True,
            },
            "delete_strategy",
        ),
    ],
)
def test_parent_strategy_mutations_are_exact_revision_bound_commands(
    route_client: tuple[TestClient, _Service],
    suffix: str,
    intent: str,
    body: dict[str, Any],
    method: str,
) -> None:
    client, service = route_client
    response = client.post(
        f"/api/v1/parent-strategies/{STRATEGY_ID}/{suffix}",
        headers=_headers(
            key=f"parent-{suffix}",
            intent=intent,
        ),
        json=body,
    )

    assert response.status_code == 200
    assert service.calls[-1][0] == method
    assert service.calls[-1][1]["strategy_id"] == STRATEGY_ID
    assert response.json()["exchange_mutation_count"] == 0


def test_parent_strategy_errors_are_fixed_and_value_blind(
    route_client: tuple[TestClient, _Service],
) -> None:
    client, service = route_client
    service.error_code = "parent_strategy_delete_blocked"
    response = client.post(
        f"/api/v1/parent-strategies/{STRATEGY_ID}/delete",
        headers=_headers(
            key="parent-delete-blocked",
            intent="delete_parent_strategy",
        ),
        json={
            "expected_revision": 2,
            "operator_reason": "Delete reviewed unused strategy",
            "confirm_parent_strategy_delete": True,
        },
    )

    assert response.status_code == 409
    assert response.json()["message"] == "parent_strategy_delete_blocked"
    assert response.json()["strategy"] is None
    assert response.json()["exchange_call_count"] == 0


def test_parent_strategy_openapi_discriminates_event_evidence_semantics() -> None:
    schemas = _APP.openapi()["components"]["schemas"]
    event_schema = schemas["ParentStrategyEvent"]

    assert event_schema["discriminator"]["propertyName"] == "event_type"
    assert set(event_schema["discriminator"]["mapping"]) == {
        "PARENT_STRATEGY_CREATED",
        "PARENT_STRATEGY_EDITED",
        "PARENT_STRATEGY_DEACTIVATED",
        "PARENT_STRATEGY_DELETED",
        "PARENT_STRATEGY_MATERIALIZED",
    }
    assert len(event_schema["oneOf"]) == 5
    assert schemas["ParentStrategyCreatedEvent"]["properties"]["revision"] == {
        "type": "integer",
        "const": 1,
        "title": "Revision",
    }
    assert schemas["ParentStrategyEditedEvent"]["properties"]["evidence"] == {
        "$ref": "#/components/schemas/ParentStrategyEditedRevisionEvidence",
    }
    assert set(
        schemas["ParentStrategyEditedRevisionEvidence"]["properties"][
            "lifecycle_state"
        ]["enum"]
    ) == {"ACTIVE", "DEACTIVATED"}
    assert schemas["ParentStrategyDeactivatedRevisionEvidence"]["properties"][
        "lifecycle_state"
    ]["const"] == "DEACTIVATED"
    assert schemas["ParentStrategyDeletedRevisionEvidence"]["properties"][
        "lifecycle_state"
    ]["const"] == "DELETED"
    assert schemas["ParentStrategyMaterializedEvidence"]["properties"][
        "use_count"
    ]["minimum"] == 1
