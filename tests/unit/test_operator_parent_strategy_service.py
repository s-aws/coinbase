from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from application.admin_api.operator_parent_strategy import (
    OperatorParentStrategyError,
)
from application.admin_api.operator_parent_strategy_service import (
    OperatorParentStrategyService,
    ParentStrategyCreateRequest,
    ParentStrategyDetailResponse,
    ParentStrategyDeactivateRequest,
    ParentStrategyDeleteRequest,
    ParentStrategyEditRequest,
    ParentStrategyEvent,
)


STRATEGY_ID = "11111111-1111-4111-8111-111111111111"
PORTFOLIO_ID = "22222222-2222-4222-8222-222222222222"


def _record() -> dict[str, object]:
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
        "lifecycle_state": "ACTIVE",
        "revision": 1,
        "use_count": 0,
        "materialized_root_client_order_id": None,
        "unused_or_terminal": True,
        "active_placement_count": 0,
        "child_count": 0,
        "unresolved_claim_count": 0,
        "reconciliation_required": False,
        "delete_allowed": False,
        "delete_blockers": ["parent_strategy_not_deactivated"],
        "allowed_actions": ["EDIT", "DEACTIVATE"],
        "created_at": "2026-07-23T00:00:00+00:00",
        "updated_at": "2026-07-23T00:00:00+00:00",
    }


class FakeRepository:
    def __init__(self) -> None:
        self.record = _record()
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.product_allowed = True

    def list_strategies(self, **kwargs: object) -> tuple[list[dict[str, object]], int]:
        self.calls.append(("list", dict(kwargs)))
        return [deepcopy(self.record)], 1

    def get_strategy(self, strategy_id: str) -> dict[str, object]:
        self.calls.append(("get", {"strategy_id": strategy_id}))
        if strategy_id != STRATEGY_ID:
            raise OperatorParentStrategyError("parent_strategy_not_found")
        return deepcopy(self.record)

    def list_commands(
        self,
        **kwargs: object,
    ) -> tuple[list[dict[str, object]], int]:
        self.calls.append(("commands", dict(kwargs)))
        return [], 0

    def product_is_active_spot(self, product_id: str) -> bool:
        self.calls.append(("product", {"product_id": product_id}))
        return self.product_allowed

    def create_strategy(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(("create", dict(kwargs)))
        if not self.product_allowed:
            raise OperatorParentStrategyError(
                "parent_strategy_product_not_enabled"
            )
        return deepcopy(self.record)

    def edit_strategy(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(("edit", dict(kwargs)))
        record = deepcopy(self.record)
        record.update(
            target_movement=str(kwargs["terms"].target_movement),
            revision=2,
        )
        return record

    def deactivate_strategy(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(("deactivate", dict(kwargs)))
        record = deepcopy(self.record)
        record.update(
            lifecycle_state="DEACTIVATED",
            revision=2,
            delete_allowed=True,
            delete_blockers=[],
            allowed_actions=["EDIT", "DELETE"],
        )
        return record

    def delete_strategy(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(("delete", dict(kwargs)))
        record = deepcopy(self.record)
        record.update(
            lifecycle_state="DELETED",
            revision=3,
            delete_allowed=False,
            delete_blockers=["parent_strategy_deleted"],
            allowed_actions=[],
        )
        return record

    def record_rejected_request(self, **kwargs: object) -> None:
        self.calls.append(("record_rejected", dict(kwargs)))


def _service(repository: FakeRepository | None = None) -> tuple[
    OperatorParentStrategyService,
    FakeRepository,
]:
    repo = repository or FakeRepository()
    return (
        OperatorParentStrategyService(
            repository=repo,
            configured_spot_portfolio_id=PORTFOLIO_ID,
        ),
        repo,
    )


def _create_body() -> ParentStrategyCreateRequest:
    return ParentStrategyCreateRequest(
        name="BTC follow-up parent",
        product_id="BTC-USDC",
        side="BUY",
        reference_size="0.0001",
        reference_price="60000",
        target_movement="0.005",
        target_movement_type="P",
        max_order_replacement=2,
        allow_partial_fills=False,
        child_order_type="LIMIT",
        child_time_in_force="GOOD_UNTIL_CANCELLED",
        child_post_only=True,
        operator_reason="Create reviewed parent strategy",
        confirm_parent_strategy_create=True,
    )


def test_create_requires_backend_product_policy_and_returns_zero_exchange_authority() -> None:
    service, repository = _service()

    response = service.create_strategy(
        body=_create_body(),
        actor_id="operator-1",
        correlation_id="corr-parent-create",
        idempotency_key="idem-parent-create",
    )

    assert response.status == "accepted"
    assert response.strategy is not None
    assert response.strategy.strategy_id == STRATEGY_ID
    assert response.exchange_call_count == 0
    assert response.exchange_mutation_count == 0
    assert [name for name, _ in repository.calls] == ["create"]
    create_call = repository.calls[-1][1]
    assert create_call["portfolio_scope_sha256"] != PORTFOLIO_ID
    assert len(str(create_call["portfolio_scope_sha256"])) == 64
    assert "configured_spot_portfolio_id" not in create_call


def test_create_allowlists_public_readback_from_real_repository_row() -> None:
    repository = FakeRepository()
    repository.record.update(
        created_by="operator-1",
        deleted_at=None,
        command_replayed=False,
    )
    service, _ = _service(repository)

    response = service.create_strategy(
        body=_create_body(),
        actor_id="operator-1",
        correlation_id="corr-parent-create-real-row",
        idempotency_key="idem-parent-create-real-row",
    )

    assert response.status == "accepted"
    assert response.strategy is not None
    public_readback = response.strategy.model_dump()
    assert "created_by" not in public_readback
    assert "deleted_at" not in public_readback
    assert "command_replayed" not in public_readback


def test_create_rejects_product_not_enabled_by_backend_catalog() -> None:
    repository = FakeRepository()
    repository.product_allowed = False
    service, _ = _service(repository)

    with pytest.raises(OperatorParentStrategyError) as exc_info:
        service.create_strategy(
            body=_create_body(),
            actor_id="operator-1",
            correlation_id="corr-parent-create",
            idempotency_key="idem-parent-create",
        )

    assert exc_info.value.code == "parent_strategy_product_not_enabled"
    assert [name for name, _ in repository.calls] == ["create"]


def test_service_validation_rejection_is_durably_journaled() -> None:
    service, repository = _service()
    body = _create_body().model_copy(update={"name": "invalid\u0001name"})

    with pytest.raises(OperatorParentStrategyError) as exc_info:
        service.create_strategy(
            body=body,
            actor_id="operator-1",
            correlation_id="corr-parent-invalid-name",
            idempotency_key="idem-parent-invalid-name",
        )

    assert exc_info.value.code == "parent_strategy_name_invalid"
    assert [name for name, _ in repository.calls] == [
        "record_rejected",
    ]
    assert repository.calls[0][1] == {
        "operation": "CREATE",
        "strategy_id": None,
        "request_payload": body.model_dump(mode="json"),
        "actor_id": "operator-1",
        "operator_reason": body.operator_reason,
        "correlation_id": "corr-parent-invalid-name",
        "idempotency_key": "idem-parent-invalid-name",
        "diagnostic_code": "parent_strategy_name_invalid",
    }


def test_edit_forwards_only_allowlisted_mutable_policy_fields() -> None:
    service, repository = _service()
    body = ParentStrategyEditRequest(
        expected_revision=1,
        name="BTC follow-up parent v2",
        target_movement="0.006",
        target_movement_type="A",
        max_order_replacement=3,
        allow_partial_fills=True,
        child_order_type="LIMIT",
        child_time_in_force="GOOD_UNTIL_CANCELLED",
        child_post_only=True,
        operator_reason="Adjust reviewed child policy",
        confirm_parent_strategy_edit=True,
    )

    response = service.edit_strategy(
        strategy_id=STRATEGY_ID,
        body=body,
        actor_id="operator-1",
        correlation_id="corr-parent-edit",
        idempotency_key="idem-parent-edit",
    )

    assert response.status == "accepted"
    call = repository.calls[-1]
    assert call[0] == "edit"
    assert set(call[1]) == {
        "strategy_id",
        "expected_revision",
        "name",
        "terms",
        "actor_id",
        "operator_reason",
        "correlation_id",
        "idempotency_key",
        "acknowledgement",
    }
    assert call[1]["terms"].target_movement_type == "A"


def test_edit_name_validation_rejection_is_durably_journaled() -> None:
    service, repository = _service()
    body = ParentStrategyEditRequest(
        expected_revision=1,
        name="invalid\u0001name",
        target_movement="0.006",
        target_movement_type="A",
        max_order_replacement=3,
        allow_partial_fills=True,
        child_order_type="LIMIT",
        child_time_in_force="GOOD_UNTIL_CANCELLED",
        child_post_only=True,
        operator_reason="Adjust reviewed child policy",
        confirm_parent_strategy_edit=True,
    )

    with pytest.raises(OperatorParentStrategyError) as exc_info:
        service.edit_strategy(
            strategy_id=STRATEGY_ID,
            body=body,
            actor_id="operator-1",
            correlation_id="corr-parent-invalid-edit-name",
            idempotency_key="idem-parent-invalid-edit-name",
        )

    assert exc_info.value.code == "parent_strategy_name_invalid"
    assert [name for name, _ in repository.calls] == [
        "get",
        "record_rejected",
    ]
    assert repository.calls[-1][1] == {
        "operation": "EDIT",
        "strategy_id": STRATEGY_ID,
        "request_payload": body.model_dump(mode="json"),
        "actor_id": "operator-1",
        "operator_reason": body.operator_reason,
        "correlation_id": "corr-parent-invalid-edit-name",
        "idempotency_key": "idem-parent-invalid-edit-name",
        "diagnostic_code": "parent_strategy_name_invalid",
    }


@pytest.mark.parametrize(
    ("event_type", "revision", "evidence"),
    [
        (
            "PARENT_STRATEGY_CREATED",
            1,
            {
                "lifecycle_state": "DELETED",
                "child_order_type": "LIMIT",
                "child_time_in_force": "GOOD_UNTIL_CANCELLED",
                "child_post_only": True,
            },
        ),
        (
            "PARENT_STRATEGY_EDITED",
            2,
            {"lifecycle_state": "ACTIVE", "revision": 3},
        ),
        (
            "PARENT_STRATEGY_DEACTIVATED",
            2,
            {"lifecycle_state": "ACTIVE", "revision": 2},
        ),
        (
            "PARENT_STRATEGY_DELETED",
            3,
            {"lifecycle_state": "DEACTIVATED", "revision": 3},
        ),
        (
            "PARENT_STRATEGY_MATERIALIZED",
            1,
            {"use_count": 0},
        ),
    ],
)
def test_event_contract_rejects_semantically_contradictory_evidence(
    event_type: str,
    revision: int,
    evidence: dict[str, object],
) -> None:
    payload = {
        "strategy": _record(),
        "events": [
            {
                "event_id": "44444444-4444-4444-8444-444444444444",
                "event_type": event_type,
                "revision": revision,
                "actor_id": "operator-1",
                "correlation_id": "corr-parent-event",
                "evidence": evidence,
                "recorded_at": "2026-07-23T00:00:00+00:00",
            }
        ],
        "event_total_count": 1,
        "event_limit": 25,
        "event_offset": 0,
        "event_next_offset": None,
    }

    with pytest.raises(ValidationError):
        ParentStrategyDetailResponse.model_validate(payload)


def test_event_contract_accepts_revision_bound_deactivated_edit() -> None:
    event = ParentStrategyEvent.model_validate(
        {
            "event_id": "44444444-4444-4444-8444-444444444444",
            "event_type": "PARENT_STRATEGY_EDITED",
            "revision": 3,
            "actor_id": "operator-1",
            "correlation_id": "corr-parent-deactivated-edit",
            "evidence": {
                "lifecycle_state": "DEACTIVATED",
                "revision": 3,
            },
            "recorded_at": "2026-07-23T00:00:00+00:00",
        }
    )

    assert event.model_dump()["evidence"] == {
        "lifecycle_state": "DEACTIVATED",
        "revision": 3,
    }


def test_deactivate_and_delete_are_distinct_revision_bound_commands() -> None:
    service, repository = _service()

    deactivated = service.deactivate_strategy(
        strategy_id=STRATEGY_ID,
        body=ParentStrategyDeactivateRequest(
            expected_revision=1,
            operator_reason="Stop future use",
            confirm_parent_strategy_deactivate=True,
        ),
        actor_id="operator-1",
        correlation_id="corr-parent-deactivate",
        idempotency_key="idem-parent-deactivate",
    )
    deleted = service.delete_strategy(
        strategy_id=STRATEGY_ID,
        body=ParentStrategyDeleteRequest(
            expected_revision=2,
            operator_reason="Delete unused deactivated strategy",
            confirm_parent_strategy_delete=True,
        ),
        actor_id="operator-1",
        correlation_id="corr-parent-delete",
        idempotency_key="idem-parent-delete",
    )

    assert deactivated.strategy is not None
    assert deactivated.strategy.lifecycle_state == "DEACTIVATED"
    assert deleted.strategy is not None
    assert deleted.strategy.lifecycle_state == "DELETED"
    assert [name for name, _ in repository.calls[-2:]] == [
        "deactivate",
        "delete",
    ]
