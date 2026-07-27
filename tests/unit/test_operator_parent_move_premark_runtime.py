from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Any

import pytest

from application.admin_api.operator_parent_move_premark_runtime import (
    FailClosedParentMoveRuntime,
    LocalParentMovePlanningTerms,
    OperatorParentMovePremarkApiService,
    build_operator_parent_move_premark_api_service,
)
from application.admin_api.operator_parent_move_premark_policy import (
    POLICY_REVISION,
    ParentMovePremarkPolicyTerms,
    build_parent_move_premark_plan,
)
from application.admin_api.operator_parent_move_premark_service import (
    OperatorParentMoveServiceError,
)


SOURCE_ID = "11111111-1111-4111-8111-111111111111"
PORTFOLIO_ID = "22222222-2222-4222-8222-222222222222"


@dataclass
class _Goal12:
    portfolio_id_sha256: str | None


class _SourceRepository:
    def __init__(self, *, portfolio_hash: str) -> None:
        self.goal = _Goal12(portfolio_id_sha256=portfolio_hash)
        self.read_count = 0

    def read_goal(self) -> _Goal12:
        self.read_count += 1
        return self.goal

    def get_order(self, client_order_id: str) -> dict[str, Any] | None:
        self.read_count += 1
        if client_order_id != SOURCE_ID:
            return None
        return {
            "client_order_id": SOURCE_ID,
            "product_id": "BTC-USDC",
            "side": "BUY",
            "status": "OPEN",
            "order_type": "LIMIT",
            "time_in_force": "GOOD_UNTIL_CANCELLED",
            "size": "0.00001",
            "limit_price": "50000",
            "filled_size": "0",
            "ownership_provenance": "ADMIN_MANUAL_ROOT",
            "authoritatively_nonterminal": True,
            "cancel_eligible": True,
        }


class _ProductRepository:
    def get_active_revision_id(self) -> str:
        return "33333333-3333-4333-8333-333333333333"

    def list_revision_products(
        self, revision_id: str
    ) -> list[dict[str, Any]]:
        assert revision_id
        return [
            {
                "product_id": "BTC-USDC",
                "product_type": "SPOT",
                "base_increment": "0.00000001",
                "price_increment": "0.01",
                "base_min_size": "0.00000001",
                "quote_min_size": "0.01",
                "exchange_status": "ONLINE",
                "exchange_disabled": False,
                "cancel_only": False,
                "view_only": False,
                "lifecycle": "ENABLED",
            }
        ]


class _GoalRepository:
    def __init__(self) -> None:
        self.read_count = 0

    def get_goal(self, source_client_order_id: str):
        self.read_count += 1
        return None


class _ProjectionService:
    def __init__(self, projection: dict[str, Any]) -> None:
        self.projection = projection

    def get_execution(self, source_client_order_id: str):
        assert source_client_order_id == SOURCE_ID
        return self.projection


class _MissingSourceRepository:
    def get_order(self, client_order_id: str):
        assert client_order_id == SOURCE_ID
        return None


def _service(
    *,
    portfolio_hash: str | None = None,
):
    exact_hash = portfolio_hash or hashlib.sha256(
        PORTFOLIO_ID.encode()
    ).hexdigest()
    return build_operator_parent_move_premark_api_service(
        goal_repository=_GoalRepository(),
        source_repository=_SourceRepository(
            portfolio_hash=exact_hash,
        ),
        product_catalog_repository=_ProductRepository(),
        configured_portfolio_id=PORTFOLIO_ID,
        legacy_pending_move_checker=lambda _source_id: False,
        execution_authority_checker=lambda: True,
    )


def test_local_readback_proves_planning_terms_without_coinbase() -> None:
    service = _service()

    response = service.readback(SOURCE_ID, allow_premark=True)

    assert response.state == "UNCONSUMED"
    assert response.diagnostic_code == "operator_parent_move_source_eligible"
    assert response.allowed_actions == ["PREMARK"]
    assert response.planning_terms_complete is True
    assert response.live_authority_terms_complete is False
    assert response.execution_authority_enabled is True
    assert response.page_load_coinbase_calls == 0
    assert response.source_selection.eligible is True
    assert response.source_selection.portfolio_scope_sha256 == hashlib.sha256(
        PORTFOLIO_ID.encode()
    ).hexdigest()


def test_portfolio_binding_mismatch_fails_closed() -> None:
    response = _service(portfolio_hash="f" * 64).readback(
        SOURCE_ID,
        allow_premark=True,
    )

    assert response.allowed_actions == []
    assert response.source_selection.eligible is False
    assert response.diagnostic_code == (
        "operator_parent_move_source_portfolio_scope_mismatch"
    )


def test_fail_closed_runtime_never_crosses_boundary() -> None:
    runtime = FailClosedParentMoveRuntime()
    crossed = False

    def before_exchange_call() -> None:
        nonlocal crossed
        crossed = True

    with pytest.raises(
        OperatorParentMoveServiceError,
        match="operator_parent_move_live_authority_terms_incomplete",
    ):
        runtime.cancel_source(
            {},
            before_exchange_call=before_exchange_call,
        )

    assert crossed is False


def test_durable_plan_remains_readable_after_source_disappears() -> None:
    portfolio_hash = hashlib.sha256(PORTFOLIO_ID.encode()).hexdigest()
    terms = ParentMovePremarkPolicyTerms(
        terms_complete=True,
        policy_revision=POLICY_REVISION,
        portfolio_scope_sha256=portfolio_hash,
        approved_product_id="BTC-USDC",
        price_increment="0.01",
        base_increment="0.00000001",
        base_min_size="0.00000001",
        quote_min_size="0.01",
    )
    plan = build_parent_move_premark_plan(
        source={
            "client_order_id": SOURCE_ID,
            "parent_order_id": None,
            "ownership_provenance": "ADMIN_MANUAL_ROOT",
            "portfolio_scope_sha256": portfolio_hash,
            "product_id": "BTC-USDC",
            "side": "BUY",
            "status": "OPEN",
            "order_type": "LIMIT",
            "time_in_force": "GOOD_UNTIL_CANCELLED",
            "size": "0.00001",
            "limit_price": "50000",
            "filled_size": "0",
            "post_only_compatible": True,
            "authoritatively_nonterminal": True,
            "cancel_eligible": True,
        },
        requested_limit_price="50000.127",
        reserved_successor_client_order_id=(
            "44444444-4444-4444-8444-444444444444"
        ),
        policy_terms=terms,
        legacy_pending_move=False,
    )
    projection = {
        "source_client_order_id": SOURCE_ID,
        "plan": plan.to_persisted_payload(),
        "plan_sha256": plan.plan_sha256,
        "state": "PLANNED",
        "diagnostic_code": "operator_parent_move_plan_created",
        "cycle_count": 1,
        "latest_cycle_number": 1,
        "latest_cycle_phase": "PLAN",
        "latest_cycle_status": "COMPLETED",
        "latest_cycle_correlation_id": "goal14-plan",
        "latest_cycle_actor_id_sha256": "a" * 64,
        "latest_cycle_idempotency_key_sha256": "b" * 64,
        "latest_cycle_payload_sha256": "c" * 64,
        "latest_cycle_evidence_sha256": "d" * 64,
        "created_at": "2026-07-27T00:00:00Z",
        "updated_at": "2026-07-27T00:00:00Z",
    }
    service = OperatorParentMovePremarkApiService(
        service=_ProjectionService(projection),
        order_repository=_MissingSourceRepository(),
        planning_terms=LocalParentMovePlanningTerms(
            policy_terms=terms,
            complete=True,
            diagnostic_code="operator_parent_move_source_eligible",
        ),
        legacy_pending_move_checker=lambda _source_id: False,
        execution_authority_checker=lambda: True,
    )

    response = service.readback(SOURCE_ID, allow_premark=True)

    assert response.state == "PLANNED"
    assert response.plan is not None
    assert response.plan.source_evidence_sha256 == (
        plan.source_evidence_sha256
    )
    assert response.source_selection.found is False
    assert response.source_selection.eligible is False
    assert response.source_selection.source_evidence_sha256 is None
    assert response.allowed_actions == []
