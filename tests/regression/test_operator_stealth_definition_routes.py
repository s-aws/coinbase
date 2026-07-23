from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.v1.app import app as _APP
from api.v1.routes import operator_stealth_definition as routes
from application.admin_api.operator_stealth_definition import (
    OperatorStealthDefinitionError,
)
from application.admin_api.operator_stealth_definition_service import (
    StealthDefinitionMutationResponse,
)


pytestmark = [pytest.mark.regression, pytest.mark.serial]

DEFINITION_ID = "11111111-1111-4111-8111-111111111111"
PREVIEW_ID = "22222222-2222-4222-8222-222222222222"


def _definition(
    *,
    lifecycle_state: str = "DRAFT",
    revision: int = 1,
) -> dict[str, Any]:
    draft = lifecycle_state == "DRAFT"
    return {
        "definition_id": DEFINITION_ID,
        "name": "BTC patient bid",
        "portfolio_scope_sha256": "a" * 64,
        "admitted_product_catalog_revision_id":
            "33333333-3333-4333-8333-333333333333",
        "admitted_product_catalog_snapshot_sha256": "b" * 64,
        "product_id": "BTC-USDC",
        "side": "BUY",
        "total_size": "0.0001",
        "limit_price": "60000",
        "reveal_condition_type": "PRICE",
        "reveal_price_threshold": "59000",
        "reveal_direction": "BELOW",
        "hold_duration_seconds": 5,
        "delay_seconds": None,
        "reveal_pricing_policy": "CONFIGURED_LIMIT",
        "sizing_mode": "FIXED",
        "follow_up_reveal_direction": "OPPOSITE",
        "target_movement": "0.005",
        "target_movement_type": "P",
        "max_order_replacements": 2,
        "allow_partial_fills": False,
        "post_only": True,
        "lifecycle_state": lifecycle_state,
        "revision": revision,
        "definition_sha256": "c" * 64,
        "imported_from_preview_id": None,
        "runtime_status": None,
        "runtime_classification": "UNMATERIALIZED",
        "blocked_navigation": None,
        "local_mutation_allowed": draft,
        "allowed_actions": (
            ["EDIT", "CANCEL", "EXPORT", "CLEAR"] if draft else []
        ),
        "created_at": "2026-07-23T00:00:00+00:00",
        "updated_at": "2026-07-23T00:00:00+00:00",
        "terminal_at": None,
        "trading_authority_granted": False,
        "exchange_call_count": 0,
        "exchange_mutation_count": 0,
    }


def _response(method: str, *, lifecycle: str = "DRAFT", revision: int = 1):
    return StealthDefinitionMutationResponse(
        status="accepted",
        message=f"stealth_definition_{method}_accepted",
        service_method=method,
        definition=(
            _definition(lifecycle_state=lifecycle, revision=revision)
            if method in {
                "create_definition",
                "edit_definition",
                "cancel_definition",
            }
            else None
        ),
        definitions=(
            [_definition(lifecycle_state=lifecycle, revision=revision)]
            if method in {"clear_definitions", "apply_import"}
            else []
        ),
        cleared_count=1 if method == "clear_definitions" else 0,
        imported_count=1 if method == "apply_import" else 0,
        correlation_id=f"{method}-correlation",
        idempotency_key=f"{method}-key",
        local_state_mutated=method != "export_definitions",
    )


@dataclass
class _Service:
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    error_code: str | None = None

    def list_definitions(self, **kwargs: Any):
        self.calls.append(("list", kwargs))
        return {
            "items": [_definition()],
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

    def get_definition(self, **kwargs: Any):
        self.calls.append(("get", kwargs))
        return {
            "definition": _definition(),
            "events": [],
            "event_total_count": 0,
            "event_limit": kwargs["event_limit"],
            "event_offset": kwargs["event_offset"],
            "event_next_offset": None,
            "trading_authority_granted": False,
            "exchange_call_count": 0,
            "exchange_mutation_count": 0,
        }

    def get_import_preview(self, **kwargs: Any):
        self.calls.append(("get_preview", kwargs))
        return {
            "preview_id": PREVIEW_ID,
            "manifest_sha256": "d" * 64,
            "state": "PREVIEWED",
            "item_count": 1,
            "valid_item_count": 1,
            "all_items_valid": True,
            "items": [
                {
                    "ordinal": 1,
                    "definition_id": DEFINITION_ID,
                    "valid": True,
                    "diagnostic_code":
                        "stealth_definition_import_item_valid",
                }
            ],
            "created_at": "2026-07-23T00:00:00+00:00",
            "updated_at": "2026-07-23T00:00:00+00:00",
            "applied_at": None,
            "local_state_mutated": False,
            "trading_authority_granted": False,
            "exchange_call_count": 0,
            "exchange_mutation_count": 0,
        }

    def _mutate(self, method: str, kwargs: dict[str, Any]):
        self.calls.append((method, kwargs))
        if self.error_code:
            raise OperatorStealthDefinitionError(self.error_code)
        lifecycle = (
            "CANCELLED"
            if method == "cancel_definition"
            else "CLEARED"
            if method == "clear_definitions"
            else "DRAFT"
        )
        revision = 2 if method in {
            "edit_definition",
            "cancel_definition",
            "clear_definitions",
        } else 1
        if method == "preview_import":
            return StealthDefinitionMutationResponse(
                status="accepted",
                message="stealth_definition_import_previewed",
                service_method=method,
                preview=self.get_import_preview(preview_id=PREVIEW_ID),
                correlation_id=kwargs["correlation_id"],
                idempotency_key=kwargs["idempotency_key"],
                local_state_mutated=False,
            )
        if method == "export_definitions":
            return StealthDefinitionMutationResponse(
                status="accepted",
                message="stealth_definitions_exported",
                service_method=method,
                export={
                    "export_id":
                        "44444444-4444-4444-8444-444444444444",
                    "schema_version": "operator-stealth-definition/v1",
                    "manifest_sha256": "e" * 64,
                    "item_count": 1,
                    "items": [
                        {
                            "definition_id": DEFINITION_ID,
                            **_terms(),
                        }
                    ],
                },
                correlation_id=kwargs["correlation_id"],
                idempotency_key=kwargs["idempotency_key"],
                local_state_mutated=False,
            )
        response = _response(
            method,
            lifecycle=lifecycle,
            revision=revision,
        )
        return response.model_copy(
            update={
                "correlation_id": kwargs["correlation_id"],
                "idempotency_key": kwargs["idempotency_key"],
            }
        )

    def create_definition(self, **kwargs: Any):
        return self._mutate("create_definition", kwargs)

    def edit_definition(self, **kwargs: Any):
        return self._mutate("edit_definition", kwargs)

    def cancel_definition(self, **kwargs: Any):
        return self._mutate("cancel_definition", kwargs)

    def clear_definitions(self, **kwargs: Any):
        return self._mutate("clear_definitions", kwargs)

    def export_definitions(self, **kwargs: Any):
        return self._mutate("export_definitions", kwargs)

    def preview_import(self, **kwargs: Any):
        return self._mutate("preview_import", kwargs)

    def apply_import(self, **kwargs: Any):
        return self._mutate("apply_import", kwargs)


def _terms() -> dict[str, Any]:
    return {
        "name": "BTC patient bid",
        "product_id": "BTC-USDC",
        "side": "BUY",
        "total_size": "0.0001",
        "limit_price": "60000",
        "reveal_condition_type": "PRICE",
        "reveal_price_threshold": "59000",
        "reveal_direction": "BELOW",
        "hold_duration_seconds": 5,
        "delay_seconds": None,
        "reveal_pricing_policy": "CONFIGURED_LIMIT",
        "sizing_mode": "FIXED",
        "follow_up_reveal_direction": "OPPOSITE",
        "target_movement": "0.005",
        "target_movement_type": "P",
        "max_order_replacements": 2,
        "allow_partial_fills": False,
        "post_only": True,
    }


@pytest.fixture
def route_client(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[TestClient, _Service]:
    monkeypatch.setenv("COINBASE_ADMIN_API_AUTH_MODE", "bootstrap_bearer")
    monkeypatch.setenv(
        "COINBASE_ADMIN_API_BEARER_TOKEN",
        "local-admin-token",
    )
    monkeypatch.setenv(
        "COINBASE_ADMIN_API_OPERATOR_STEALTH_DEFINITIONS_ENABLED",
        "1",
    )
    service = _Service()
    _APP.dependency_overrides[
        routes.get_operator_stealth_definition_service
    ] = lambda: service
    with TestClient(_APP) as client:
        yield client, service
    _APP.dependency_overrides.pop(
        routes.get_operator_stealth_definition_service,
        None,
    )


def _headers(key: str, intent: str, *, roles: str = "admin,trader"):
    return {
        "Authorization": "Bearer local-admin-token",
        "X-Admin-Actor": "stealth-definition-operator",
        "X-Admin-Roles": roles,
        "Idempotency-Key": key,
        "X-Correlation-Id": f"{key}-correlation",
        "X-Operator-Intent": intent,
    }


def test_reads_are_authenticated_paginated_and_call_free(
    route_client: tuple[TestClient, _Service],
) -> None:
    client, service = route_client

    assert client.get("/api/v1/stealth/definitions").status_code == 401
    listing = client.get(
        "/api/v1/stealth/definitions?limit=25&offset=0",
        headers=_headers("read-list", "read_stealth_definitions"),
    )
    detail = client.get(
        f"/api/v1/stealth/definitions/{DEFINITION_ID}",
        headers=_headers("read-detail", "read_stealth_definition"),
    )
    preview = client.get(
        f"/api/v1/stealth/definition-import-previews/{PREVIEW_ID}",
        headers=_headers("read-preview", "read_stealth_definition_import"),
    )

    assert listing.status_code == detail.status_code == preview.status_code == 200
    assert listing.json()["exchange_call_count"] == 0
    assert detail.json()["definition"]["allowed_actions"] == [
        "EDIT", "CANCEL", "EXPORT", "CLEAR"
    ]
    assert preview.json()["state"] == "PREVIEWED"
    assert [call[0] for call in service.calls] == [
        "list", "get", "get_preview"
    ]


def test_operator_can_create_edit_cancel_and_clear_only_through_exact_intents(
    route_client: tuple[TestClient, _Service],
) -> None:
    client, service = route_client

    create = client.post(
        "/api/v1/stealth/definitions",
        headers=_headers(
            "create-definition",
            "create_stealth_definition",
        ),
        json={
            **_terms(),
            "definition_id": None,
            "operator_reason": "create reviewed definition",
            "confirm_stealth_definition_create": True,
        },
    )
    edit = client.post(
        f"/api/v1/stealth/definitions/{DEFINITION_ID}/edit",
        headers=_headers("edit-definition", "edit_stealth_definition"),
        json={
            **_terms(),
            "expected_revision": 1,
            "operator_reason": "edit reviewed definition",
            "confirm_stealth_definition_edit": True,
        },
    )
    cancel = client.post(
        f"/api/v1/stealth/definitions/{DEFINITION_ID}/cancel",
        headers=_headers(
            "cancel-definition",
            "cancel_stealth_definition",
        ),
        json={
            "expected_revision": 1,
            "operator_reason": "cancel local definition",
            "confirm_stealth_definition_cancel": True,
        },
    )
    clear = client.post(
        "/api/v1/stealth/definitions/clear",
        headers=_headers("clear-definitions", "clear_stealth_definitions"),
        json={
            "selections": [
                {
                    "definition_id": DEFINITION_ID,
                    "expected_revision": 1,
                }
            ],
            "operator_reason": "clear selected definitions",
            "confirm_stealth_definition_clear": True,
        },
    )

    assert [response.status_code for response in (create, edit, cancel, clear)] == [
        200, 200, 200, 200
    ]
    assert clear.json()["cleared_count"] == 1
    assert all(response.json()["exchange_call_count"] == 0 for response in (
        create, edit, cancel, clear
    ))
    assert [call[0] for call in service.calls] == [
        "create_definition",
        "edit_definition",
        "cancel_definition",
        "clear_definitions",
    ]


def test_export_preview_and_apply_import_are_operator_actions(
    route_client: tuple[TestClient, _Service],
) -> None:
    client, _ = route_client

    exported = client.post(
        "/api/v1/stealth/definition-exports",
        headers=_headers(
            "export-definitions",
            "export_stealth_definitions",
        ),
        json={
            "definition_ids": [DEFINITION_ID],
            "operator_reason": "export reviewed definition",
            "confirm_stealth_definition_export": True,
        },
    )
    previewed = client.post(
        "/api/v1/stealth/definition-import-previews",
        headers=_headers(
            "preview-import",
            "preview_stealth_definition_import",
        ),
        json={
            "items": [{"definition_id": DEFINITION_ID, **_terms()}],
            "operator_reason": "preview reviewed import",
            "confirm_stealth_definition_import_preview": True,
        },
    )
    applied = client.post(
        f"/api/v1/stealth/definition-import-previews/{PREVIEW_ID}/apply",
        headers=_headers(
            "apply-import",
            "apply_stealth_definition_import",
        ),
        json={
            "expected_manifest_sha256": "d" * 64,
            "operator_reason": "apply reviewed import",
            "confirm_stealth_definition_import_apply": True,
        },
    )

    assert exported.status_code == previewed.status_code == applied.status_code == 200
    assert exported.json()["export"]["schema_version"] == (
        "operator-stealth-definition/v1"
    )
    assert previewed.json()["preview"]["all_items_valid"] is True
    assert applied.json()["imported_count"] == 1


def test_fixed_fail_closed_error_and_rbac(
    route_client: tuple[TestClient, _Service],
) -> None:
    client, service = route_client
    service.error_code = "stealth_definition_materialized"

    blocked = client.post(
        f"/api/v1/stealth/definitions/{DEFINITION_ID}/cancel",
        headers=_headers(
            "blocked-cancel",
            "cancel_stealth_definition",
        ),
        json={
            "expected_revision": 1,
            "operator_reason": "must fail closed",
            "confirm_stealth_definition_cancel": True,
        },
    )
    forbidden = client.post(
        f"/api/v1/stealth/definitions/{DEFINITION_ID}/cancel",
        headers=_headers(
            "forbidden-cancel",
            "cancel_stealth_definition",
            roles="viewer",
        ),
        json={
            "expected_revision": 1,
            "operator_reason": "viewer cannot mutate",
            "confirm_stealth_definition_cancel": True,
        },
    )

    assert blocked.status_code == 409
    assert blocked.json()["message"] == "stealth_definition_materialized"
    assert blocked.json()["exchange_call_count"] == 0
    assert forbidden.status_code == 403
