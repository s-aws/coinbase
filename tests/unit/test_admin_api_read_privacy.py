from __future__ import annotations

import json
from types import SimpleNamespace

from application.admin_api import read_service
from application.admin_api.models import AdminOrderDetailResponse
from application.admin_api.read_service import AdminApiReadService


ROOT_ID = "880e8400-e29b-41d4-a716-446655440000"
CHILD_ID = "990e8400-e29b-41d4-a716-446655440000"
STEALTH_ID = "770e8400-e29b-41d4-a716-446655440000"
PRIVATE_PORTFOLIO_ID = "11111111-2222-4333-8444-555555555555"


def _assert_no_private_read_evidence(payload: object) -> None:
    serialized = json.dumps(payload, sort_keys=True, default=str)
    assert PRIVATE_PORTFOLIO_ID not in serialized

    def visit(value: object) -> None:
        if isinstance(value, dict):
            assert "parent_row_id" not in value
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(payload)


def test_order_list_detail_and_chain_redact_internal_portfolio_and_row_ids(
    monkeypatch,
) -> None:
    import database.order as order_module

    root = {
        "parent_row_id": 73,
        "client_order_id": ROOT_ID,
        "product_id": "BTC-USDC",
        "side": "BUY",
        "status": "FILLED",
        "order_type": "limit",
        "size": "0.01",
        "price": "100",
        "parent_order_id": None,
        "retail_portfolio_id": PRIVATE_PORTFOLIO_ID,
        "ownership_provenance": "ADMIN_MANUAL_ROOT",
    }
    child = {
        "parent_row_id": 74,
        "client_order_id": CHILD_ID,
        "product_id": "BTC-USDC",
        "side": "SELL",
        "status": "HIDDEN",
        "order_type": "limit",
        "size": "0.01",
        "price": "101",
        "parent_order_id": ROOT_ID,
        "retail_portfolio_id": PRIVATE_PORTFOLIO_ID,
        "ownership_provenance": "ADMIN_FILL_FOLLOW_UP",
    }
    monkeypatch.setenv(
        "COINBASE_ADMIN_API_SPOT_PORTFOLIO_ID",
        PRIVATE_PORTFOLIO_ID,
    )
    monkeypatch.setattr(
        order_module,
        "get_parent_order",
        lambda client_order_id: root if client_order_id == ROOT_ID else child,
    )
    monkeypatch.setattr(
        order_module,
        "get_parent_order_summary",
        lambda client_order_id: root if client_order_id == ROOT_ID else child,
        raising=False,
    )
    monkeypatch.setattr(order_module, "get_parent_orders", lambda: [root, child])
    monkeypatch.setattr(
        order_module,
        "get_parent_orders_page",
        lambda **_kwargs: ([root, child], 2),
    )
    monkeypatch.setattr(
        order_module,
        "get_stealth_children_for_parent",
        lambda _parent_order_id: [],
    )
    monkeypatch.setattr(
        read_service,
        "_runtime_follow_up_claim_state",
        lambda _client_order_id: (None, "test", True),
    )
    monkeypatch.setattr(
        read_service,
        "_runtime_fill_follow_up_execution_adapter_state",
        lambda: (False, "test"),
    )

    service = AdminApiReadService()
    payloads = [
        service.build_order_list().model_dump(mode="json"),
        service.build_order_detail(client_order_id=ROOT_ID).model_dump(mode="json"),
        service.build_order_fill_follow_up_chain(
            client_order_id=ROOT_ID
        ).model_dump(mode="json"),
    ]

    for payload in payloads:
        _assert_no_private_read_evidence(payload)
    chain = payloads[-1]
    assert chain["portfolio_scope"]["scope_consistent"] is True
    assert chain["portfolio_scope"]["expected_portfolio_id"] is None
    assert chain["portfolio_scope"]["root_portfolio_id"] is None
    assert chain["portfolio_scope"]["child_portfolio_ids"] == {CHILD_ID: None}
    assert root["retail_portfolio_id"] == PRIVATE_PORTFOLIO_ID
    assert root["parent_row_id"] == 73


def test_stealth_and_movement_reads_recursively_sanitize_anchor_preparation(
    monkeypatch,
) -> None:
    import database.order as order_module

    preparation = {
        "portfolio_id": PRIVATE_PORTFOLIO_ID,
        "parent_row_id": 73,
        "controlled_plan_sha256": "a" * 64,
        "product_id": "BTC-USDC",
        "nested": {
            "retail_portfolio_id": PRIVATE_PORTFOLIO_ID,
            "safe_marker": "preserved",
        },
    }
    anchor_state = {
        "active_placement_client_order_id": "placement-client",
        "active_exchange_order_id": "exchange-evidence",
        "controlled_admin_first_child_reveal_preparation": preparation,
    }
    row = {
        "stealth_order_id": STEALTH_ID,
        "parent_order_id": ROOT_ID,
        "product_id": "BTC-USDC",
        "side": "SELL",
        "status": "REVEALED",
        "anchor_repricing_state_json": anchor_state,
    }

    def execute_query(query: str, _params: object = None) -> list[dict[str, object]]:
        return [row] if "FROM stealth_orders" in query else []

    monkeypatch.setattr(
        order_module,
        "DB_CLIENT",
        SimpleNamespace(execute_query=execute_query),
    )
    monkeypatch.setattr(order_module, "get_stealth_order_by_id", lambda _id: row)
    monkeypatch.setattr(read_service, "_runtime_mutation_claims_for", lambda _id: [])
    monkeypatch.setattr(
        read_service,
        "_replacement_slots_for",
        lambda _parent_id, _stealth_id: [],
    )

    service = AdminApiReadService()
    stealth_list = service.build_stealth_order_list().model_dump(mode="json")
    stealth_detail = service.build_stealth_order_detail(
        stealth_order_id=STEALTH_ID
    ).model_dump(mode="json")
    movement = service.build_movement_repricing_evidence().model_dump(mode="json")

    for payload in (stealth_list, stealth_detail, movement):
        _assert_no_private_read_evidence(payload)
    public_preparation = stealth_detail["order"]["anchor_repricing_state"][
        "controlled_admin_first_child_reveal_preparation"
    ]
    assert public_preparation["controlled_plan_sha256"] == "a" * 64
    assert public_preparation["product_id"] == "BTC-USDC"
    assert public_preparation["nested"] == {"safe_marker": "preserved"}
    assert preparation["portfolio_id"] == PRIVATE_PORTFOLIO_ID
    assert preparation["parent_row_id"] == 73


def test_unresolved_root_command_evidence_uses_a_fixed_public_projection() -> None:
    from application.admin_api.command_service import (
        _public_unresolved_spot_root_evidence,
    )

    raw = {
        "parent_row_id": 73,
        "client_order_id": ROOT_ID,
        "product_id": "BTC-USDC",
        "side": "BUY",
        "size": "0.01",
        "price": "100",
        "status": "SUBMISSION_UNKNOWN",
        "ownership_provenance": "ADMIN_MANUAL_ROOT",
        "retail_portfolio_id": PRIVATE_PORTFOLIO_ID,
        "correlation_id": "corr-private-proof",
        "audit_id": "audit-public-proof",
        "created_at": "2026-07-17T00:00:00+00:00",
        "unexpected_private_extension": {
            "portfolio_id": PRIVATE_PORTFOLIO_ID,
        },
    }

    public = _public_unresolved_spot_root_evidence(raw)

    assert public == {
        "client_order_id": ROOT_ID,
        "product_id": "BTC-USDC",
        "side": "BUY",
        "size": "0.01",
        "price": "100",
        "status": "SUBMISSION_UNKNOWN",
        "ownership_provenance": "ADMIN_MANUAL_ROOT",
        "correlation_id": "corr-private-proof",
        "audit_id": "audit-public-proof",
        "created_at": "2026-07-17T00:00:00+00:00",
    }
    _assert_no_private_read_evidence(public)
    assert raw["parent_row_id"] == 73
    assert raw["retail_portfolio_id"] == PRIVATE_PORTFOLIO_ID


def test_order_reads_distinguish_backend_failure_from_authoritative_absence(
    monkeypatch,
) -> None:
    import database.order as order_module

    private_exception_text = "SELECT * FROM private_operator_orders"

    def fail_read(*_args, **_kwargs):
        raise RuntimeError(private_exception_text)

    monkeypatch.setattr(order_module, "get_parent_orders_page", fail_read)
    monkeypatch.setattr(
        order_module,
        "get_parent_order_summary",
        fail_read,
        raising=False,
    )

    service = AdminApiReadService()
    order_list = service.build_order_list().model_dump(mode="json")
    order_detail = service.build_order_detail(
        client_order_id=ROOT_ID
    ).model_dump(mode="json")

    assert order_list["filters"]["backend_read_error"] == "backend_read_failed"
    assert order_detail["found"] is False
    assert order_detail["backend_read_error"] == "backend_read_failed"
    assert private_exception_text not in json.dumps(
        [order_list, order_detail],
        sort_keys=True,
    )

    monkeypatch.setattr(
        order_module,
        "get_parent_order_summary",
        lambda _client_order_id: None,
        raising=False,
    )
    absent_detail = service.build_order_detail(
        client_order_id=ROOT_ID
    ).model_dump(mode="json")

    assert absent_detail["found"] is False
    assert absent_detail["backend_read_error"] is None


def test_order_detail_backend_read_error_is_optional_in_generated_schema() -> None:
    schema = AdminOrderDetailResponse.model_json_schema()

    assert "backend_read_error" in schema["properties"]
    assert "backend_read_error" not in schema.get("required", [])
