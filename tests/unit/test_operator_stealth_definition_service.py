from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from application.admin_api.operator_stealth_definition import (
    OperatorStealthDefinitionError,
)
from application.admin_api.operator_stealth_definition_service import (
    OperatorStealthDefinitionService,
    StealthDefinitionCreateRequest,
    StealthDefinitionEditRequest,
    StealthDefinitionImportApplyRequest,
    StealthDefinitionImportPreviewRequest,
)


PORTFOLIO_ID = "11111111-1111-4111-8111-111111111111"


def _item(
    *,
    definition_id: str = "22222222-2222-4222-8222-222222222222",
    revision: int = 1,
) -> dict[str, Any]:
    return {
        "definition_id": definition_id,
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
        "lifecycle_state": "DRAFT",
        "revision": revision,
        "definition_sha256": "c" * 64,
        "imported_from_preview_id": None,
        "runtime_status": None,
        "runtime_classification": "UNMATERIALIZED",
        "blocked_navigation": None,
        "local_mutation_allowed": True,
        "allowed_actions": ["EDIT", "CANCEL", "EXPORT", "CLEAR"],
        "created_at": "2026-07-23T00:00:00+00:00",
        "updated_at": "2026-07-23T00:00:00+00:00",
        "terminal_at": None,
        "trading_authority_granted": False,
        "exchange_call_count": 0,
        "exchange_mutation_count": 0,
    }


@dataclass
class _Repository:
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    def create_definition(self, **kwargs: Any):
        self.calls.append(("create", kwargs))
        return {**_item(), "command_replayed": False}

    def edit_definition(self, **kwargs: Any):
        self.calls.append(("edit", kwargs))
        return {**_item(revision=2), "command_replayed": False}

    def create_import_preview(self, **kwargs: Any):
        self.calls.append(("preview", kwargs))
        return {
            "preview_id": "44444444-4444-4444-8444-444444444444",
            "manifest_sha256": kwargs["manifest_sha256"],
            "state": "PREVIEWED",
            "item_count": 1,
            "valid_item_count": 1,
            "all_items_valid": True,
            "items": [
                {
                    "ordinal": 1,
                    "definition_id":
                        "22222222-2222-4222-8222-222222222222",
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
            "command_replayed": False,
        }

    def apply_import_preview(self, **kwargs: Any):
        self.calls.append(("apply", kwargs))
        return {
            "definitions": [_item()],
            "imported_count": 1,
            "command_replayed": False,
            "local_state_mutated": True,
            "trading_authority_granted": False,
            "exchange_call_count": 0,
            "exchange_mutation_count": 0,
        }


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


def test_create_and_edit_hash_portfolio_and_forward_only_normalized_terms() -> None:
    repository = _Repository()
    service = OperatorStealthDefinitionService(
        repository=repository,
        configured_spot_portfolio_id=PORTFOLIO_ID,
    )

    created = service.create_definition(
        body=StealthDefinitionCreateRequest(
            **_terms(),
            definition_id=None,
            operator_reason="create reviewed definition",
            confirm_stealth_definition_create=True,
        ),
        actor_id="operator",
        correlation_id="create-correlation",
        idempotency_key="create-key",
    )
    edited = service.edit_definition(
        definition_id=created.definition.definition_id,
        body=StealthDefinitionEditRequest(
            **{**_terms(), "reveal_price_threshold": "58500"},
            expected_revision=1,
            operator_reason="edit reviewed definition",
            confirm_stealth_definition_edit=True,
        ),
        actor_id="operator",
        correlation_id="edit-correlation",
        idempotency_key="edit-key",
    )

    assert created.status == "accepted"
    assert edited.definition is not None
    assert edited.definition.revision == 2
    assert repository.calls[0][1]["portfolio_scope_sha256"] != PORTFOLIO_ID
    assert len(repository.calls[0][1]["portfolio_scope_sha256"]) == 64
    assert repository.calls[0][1]["terms"].reveal_condition_type == "PRICE"


def test_import_preview_computes_manifest_hash_backend_side() -> None:
    repository = _Repository()
    service = OperatorStealthDefinitionService(
        repository=repository,
        configured_spot_portfolio_id=PORTFOLIO_ID,
    )
    body = StealthDefinitionImportPreviewRequest(
        items=[
            {
                "definition_id":
                    "22222222-2222-4222-8222-222222222222",
                **_terms(),
            }
        ],
        operator_reason="preview reviewed import",
        confirm_stealth_definition_import_preview=True,
    )

    response = service.preview_import(
        body=body,
        actor_id="operator",
        correlation_id="preview-correlation",
        idempotency_key="preview-key",
    )

    assert response.preview is not None
    assert len(response.preview.manifest_sha256) == 64
    assert repository.calls[0][1]["manifest_sha256"] == (
        response.preview.manifest_sha256
    )


def test_import_apply_revalidates_the_current_hashed_portfolio_scope() -> None:
    repository = _Repository()
    service = OperatorStealthDefinitionService(
        repository=repository,
        configured_spot_portfolio_id=PORTFOLIO_ID,
    )

    response = service.apply_import(
        preview_id="44444444-4444-4444-8444-444444444444",
        body=StealthDefinitionImportApplyRequest(
            expected_manifest_sha256="d" * 64,
            operator_reason="apply exact reviewed import",
            confirm_stealth_definition_import_apply=True,
        ),
        actor_id="operator",
        correlation_id="apply-correlation",
        idempotency_key="apply-key",
    )

    assert response.status == "accepted"
    assert repository.calls[0][0] == "apply"
    assert repository.calls[0][1]["portfolio_scope_sha256"] == (
        service.portfolio_scope_sha256
    )


def test_service_rejects_missing_or_non_uuid_portfolio_without_leaking_value() -> None:
    with pytest.raises(OperatorStealthDefinitionError) as exc_info:
        OperatorStealthDefinitionService(
            repository=_Repository(),
            configured_spot_portfolio_id="not-a-uuid",
        )

    assert exc_info.value.code == "stealth_definition_portfolio_not_configured"
