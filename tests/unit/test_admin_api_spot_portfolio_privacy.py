from __future__ import annotations

from types import SimpleNamespace

import pytest


pytestmark = pytest.mark.usefixtures("coinbase_execution_lease")

from application.admin_api.command_service import (
    AdminApiCommandDependencies,
    AdminApiCommandService,
    exact_coinbase_order_readback,
)
from application.admin_api.models import (
    AdminApiActor,
    AdminApiCommandEnvelope,
    AdminApiRole,
    ManualOrderCommand,
    ManualOrderRequest,
)
from application.admin_api.spot_portfolio_binding import (
    evaluate_spot_test_portfolio_binding,
    serialize_public_spot_portfolio_scope,
)


TEST_PORTFOLIO_ID = "11111111-2222-4333-8444-555555555555"
OTHER_PORTFOLIO_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"


class _PermissionsClient:
    def __init__(self, portfolio_id: str) -> None:
        self.portfolio_id = portfolio_id

    def get_api_key_permissions(self) -> dict[str, object]:
        return {
            "portfolio_uuid": self.portfolio_id,
            "portfolio_type": "CONSUMER",
            "can_view": True,
            "can_trade": True,
        }

    def list_portfolios(self) -> list[dict[str, object]]:
        return [
            {
                "uuid": self.portfolio_id,
                "name": "Test",
                "type": "CONSUMER",
            }
        ]


def test_public_spot_portfolio_serializer_redacts_ids_but_binding_retains_them() -> None:
    evidence = evaluate_spot_test_portfolio_binding(
        rest_client=_PermissionsClient(TEST_PORTFOLIO_ID),
        expected_portfolio_id=TEST_PORTFOLIO_ID,
    )

    public_scope = serialize_public_spot_portfolio_scope(evidence)

    assert evidence.expected_portfolio_id == TEST_PORTFOLIO_ID
    assert evidence.observed_portfolio_id == TEST_PORTFOLIO_ID
    assert evidence.to_dict()["portfolio_id"] == TEST_PORTFOLIO_ID
    assert public_scope["expected_portfolio_id"] is None
    assert public_scope["observed_portfolio_id"] is None
    assert public_scope["portfolio_id"] is None
    assert TEST_PORTFOLIO_ID not in repr(public_scope)


def test_binding_rejection_command_evidence_never_serializes_portfolio_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COINBASE_EXECUTION_ENABLED", "1")
    service = AdminApiCommandService(
        AdminApiCommandDependencies(
            rest_client=_PermissionsClient(OTHER_PORTFOLIO_ID),
            rest_client_available=True,
            live_runtime_enabled=True,
            command_runtime_ready=True,
            spot_portfolio_id=TEST_PORTFOLIO_ID,
            spot_portfolio_label="Test",
        )
    )
    command = ManualOrderCommand(
        envelope=AdminApiCommandEnvelope(
            idempotency_key="privacy-binding-idempotency",
            correlation_id="privacy-binding-correlation",
            operator_intent="bounded_spot_test_order",
            actor=AdminApiActor(
                actor_id="operator-privacy-test",
                roles=[AdminApiRole.ADMIN],
            ),
        ),
        request=ManualOrderRequest.model_validate(
            {
                "client_order_id": "privacy-binding-client-order",
                "product_id": "BTC-USDC",
                "side": "BUY",
                "order_type": "LIMIT",
                "base_size": "0.00002",
                "limit_price": "65000.00",
                "post_only": True,
                "time_in_force": "GOOD_UNTIL_CANCELLED",
                "manual_live_acknowledgement": True,
            }
        ),
        admin_cap_guard_decision_id="privacy-binding-cap",
        admin_max_submitted_notional_usdc="9.99",
        allow_live_execution=True,
    )

    response = service.place_manual_order(command)
    serialized = response.model_dump(mode="json")

    assert serialized["data"]["portfolio_scope"]["expected_portfolio_id"] is None
    assert serialized["data"]["portfolio_scope"]["observed_portfolio_id"] is None
    assert serialized["data"]["portfolio_scope"]["portfolio_id"] is None
    assert TEST_PORTFOLIO_ID not in repr(serialized)
    assert OTHER_PORTFOLIO_ID not in repr(serialized)


def test_selected_root_order_readback_omits_retail_portfolio_id() -> None:
    rest_client = SimpleNamespace(
        get_order=lambda _order_id: {
            "order": {
                "client_order_id": "selected-root-client-order",
                "order_id": "selected-root-exchange-order",
                "status": "OPEN",
                "product_id": "BTC-USDC",
                "product_type": "SPOT",
                "retail_portfolio_id": TEST_PORTFOLIO_ID,
                "side": "BUY",
            }
        }
    )

    readback = exact_coinbase_order_readback(
        rest_client,
        client_order_id="selected-root-client-order",
        exchange_order_id="selected-root-exchange-order",
        product_id="BTC-USDC",
        expected_retail_portfolio_id=TEST_PORTFOLIO_ID,
    )

    assert "retail_portfolio_id" not in readback["matched_order"]
    assert readback["retail_portfolio_id_matches_expected"] is True
    assert TEST_PORTFOLIO_ID not in repr(readback)
