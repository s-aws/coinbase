from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

from application.admin_api import read_service
from core.enums import OrderOwnershipProvenance, StealthLifecycleEvent


ROOT_ID = "880e8400-e29b-41d4-a716-446655440000"
CHILD_ID = str(
    uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"coinbase://filled-follow-up/{ROOT_ID}/{ROOT_ID}",
    )
)
TEST_PORTFOLIO_ID = "11111111-2222-4333-8444-555555555555"


def _filled_root(provenance: str | None) -> dict[str, object]:
    return {
        "client_order_id": ROOT_ID,
        "product_id": "BTC-USDC",
        "side": "BUY",
        "status": "FILLED",
        "size": "0.01",
        "price": "100",
        "parent_order_id": None,
        "retail_portfolio_id": TEST_PORTFOLIO_ID,
        "correlation_id": "corr-root",
        "audit_id": "audit-root",
        "exchange_order_id": "exchange-root-1",
        "ownership_provenance": provenance,
    }


def _patch_automatic_evidence(monkeypatch) -> None:
    monkeypatch.setenv("COINBASE_ADMIN_API_SPOT_PORTFOLIO_ID", TEST_PORTFOLIO_ID)
    monkeypatch.setattr(
        read_service,
        "_runtime_follow_up_claim_state",
        lambda _client_order_id: ("done", "test.claim_state", True),
    )
    monkeypatch.setattr(
        read_service,
        "_runtime_fill_follow_up_execution_adapter_state",
        lambda: (True, "test.execution_adapter"),
    )
    monkeypatch.setattr(
        read_service,
        "_order_follow_up_chain_ids",
        lambda **_kwargs: [CHILD_ID],
    )
    monkeypatch.setattr(
        read_service,
        "evaluate_spot_follow_up_policy",
        lambda **_kwargs: SimpleNamespace(
            allowed=True,
            intent="profit_take",
            reason="allowed",
            product_type="SPOT",
        ),
    )


def test_order_item_exposes_ownership_and_blocked_reveal_evidence() -> None:
    item = read_service._order_item_from_row(
        {
            **_filled_root(
                OrderOwnershipProvenance.ADMIN_MANUAL_ROOT.value
            ),
            "last_lifecycle_event": StealthLifecycleEvent.PLACEMENT_BLOCKED.value,
            "failure_reason": "standing_price_limit_exceeded",
        }
    )

    assert item.ownership_provenance == (
        OrderOwnershipProvenance.ADMIN_MANUAL_ROOT
    )
    assert item.last_lifecycle_event == StealthLifecycleEvent.PLACEMENT_BLOCKED
    assert item.failure_reason == "standing_price_limit_exceeded"
    assert item.exchange_order_id == "exchange-root-1"
    assert item.source == "order_parent"


def test_order_item_source_requires_authoritative_collection_context() -> None:
    row = {**_filled_root(None), "source": "stealth_orders"}

    parent_item = read_service._order_item_from_row(row)
    stealth_item = read_service._order_item_from_row(
        row,
        authoritative_source="stealth_orders",
    )

    assert parent_item.source == "order_parent"
    assert stealth_item.source == "stealth_orders"


def test_automatic_complete_proof_requires_admin_root_provenance(monkeypatch) -> None:
    _patch_automatic_evidence(monkeypatch)

    for provenance in (
        None,
        OrderOwnershipProvenance.EXTERNAL_WS_OBSERVED.value,
        "UNKNOWN_LEGACY_VALUE",
    ):
        audit = read_service._order_fill_follow_up_decision_audit(
            _filled_root(provenance),
            client_order_id=ROOT_ID,
        )

        assert audit is not None
        assert audit.automatic_fill_event_processing_enabled is False
        assert audit.follow_up_decision != "automatic_child_created"
        assert "admin_manual_root_ownership_provenance_missing" in (
            audit.automatic_fill_event_processing_blockers
        )


def test_automatic_complete_proof_accepts_exact_admin_root_provenance(
    monkeypatch,
) -> None:
    _patch_automatic_evidence(monkeypatch)

    audit = read_service._order_fill_follow_up_decision_audit(
        _filled_root(OrderOwnershipProvenance.ADMIN_MANUAL_ROOT.value),
        client_order_id=ROOT_ID,
    )

    assert audit is not None
    assert audit.ownership_provenance == (
        OrderOwnershipProvenance.ADMIN_MANUAL_ROOT
    )
    assert audit.automatic_fill_event_processing_enabled is True
    assert audit.follow_up_decision == "automatic_child_created"


def test_automatic_complete_proof_survives_runtime_restart_from_durable_child(
    monkeypatch,
) -> None:
    root = _filled_root(OrderOwnershipProvenance.ADMIN_MANUAL_ROOT.value)
    child = {
        "client_order_id": CHILD_ID,
        "product_id": "BTC-USDC",
        "side": "SELL",
        "status": "PENDING",
        "size": "0.01",
        "price": "101",
        "parent_order_id": ROOT_ID,
        "retail_portfolio_id": TEST_PORTFOLIO_ID,
        "exchange_order_id": None,
        "ownership_provenance": (
            OrderOwnershipProvenance.ADMIN_FILL_FOLLOW_UP.value
        ),
    }
    monkeypatch.setenv("COINBASE_ADMIN_API_SPOT_PORTFOLIO_ID", TEST_PORTFOLIO_ID)
    monkeypatch.setattr(
        read_service,
        "_runtime_follow_up_claim_state",
        lambda _client_order_id: (
            None,
            "runtime_orderbook_unavailable",
            False,
        ),
    )
    monkeypatch.setattr(
        read_service,
        "_runtime_fill_follow_up_execution_adapter_state",
        lambda: (False, "runtime_order_engine_unavailable"),
    )
    monkeypatch.setattr(
        "database.order.get_parent_orders",
        lambda: [root, child],
    )
    monkeypatch.setattr(
        read_service,
        "evaluate_spot_follow_up_policy",
        lambda **_kwargs: SimpleNamespace(
            allowed=True,
            intent="exit",
            reason="allowed",
            product_type="SPOT",
        ),
    )

    audit = read_service._order_fill_follow_up_decision_audit(
        root,
        client_order_id=ROOT_ID,
    )

    assert audit is not None
    assert audit.claim_state == "done"
    assert audit.claim_state_source == (
        "order_parent.durable_admin_fill_follow_up"
    )
    assert audit.claim_reader_ran is True
    assert audit.automatic_fill_event_processing_enabled is True
    assert audit.existing_follow_up_client_order_ids == [CHILD_ID]
    assert audit.existing_follow_up_count == 1
    assert audit.follow_up_decision == "automatic_child_created"


def test_durable_completion_rejects_non_deterministic_admin_child(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "database.order.get_parent_orders",
        lambda: [
            {
                "client_order_id": "990e8400-e29b-41d4-a716-446655440000",
                "product_id": "BTC-USDC",
                "side": "SELL",
                "status": "CANCELLED",
                "parent_order_id": ROOT_ID,
                "retail_portfolio_id": TEST_PORTFOLIO_ID,
                "exchange_order_id": "exchange-unrelated-child",
                "ownership_provenance": (
                    OrderOwnershipProvenance.ADMIN_FILL_FOLLOW_UP.value
                ),
            }
        ],
    )

    assert read_service._durable_automatic_fill_follow_up_ids(
        root_parent_client_order_id=ROOT_ID,
        product_id="BTC-USDC",
        follow_up_side="SELL",
        retail_portfolio_id=TEST_PORTFOLIO_ID,
    ) == []


def test_operator_visible_chain_remains_after_submission_and_terminal_reconciliation(
    monkeypatch,
) -> None:
    root = _filled_root(OrderOwnershipProvenance.ADMIN_MANUAL_ROOT.value)
    child = {
        "client_order_id": CHILD_ID,
        "product_id": "BTC-USDC",
        "side": "SELL",
        "status": "OPEN",
        "size": "0.01",
        "price": "160.00",
        "parent_order_id": ROOT_ID,
        "retail_portfolio_id": TEST_PORTFOLIO_ID,
        "correlation_id": "corr-root",
        "audit_id": "audit-root",
        "exchange_order_id": "exchange-child-1",
        "ownership_provenance": (
            OrderOwnershipProvenance.ADMIN_FILL_FOLLOW_UP.value
        ),
    }
    stealth_child = {
        "client_order_id": CHILD_ID,
        "product_id": "BTC-USDC",
        "side": "SELL",
        "size": "0.01",
        "price": "160.00",
        "parent_order_id": ROOT_ID,
        "stealth_status": "REVEALED",
        "last_lifecycle_event": StealthLifecycleEvent.REVEAL_SUCCEEDED.value,
        "failure_reason": None,
    }

    monkeypatch.setenv("COINBASE_ADMIN_API_SPOT_PORTFOLIO_ID", TEST_PORTFOLIO_ID)
    monkeypatch.setattr(
        read_service,
        "_runtime_follow_up_claim_state",
        lambda _client_order_id: (
            None,
            "runtime_orderbook_unavailable",
            False,
        ),
    )
    monkeypatch.setattr(
        read_service,
        "_runtime_fill_follow_up_execution_adapter_state",
        lambda: (False, "runtime_order_engine_unavailable"),
    )
    monkeypatch.setattr(
        "database.order.get_parent_order",
        lambda client_order_id: root if client_order_id == ROOT_ID else None,
    )
    monkeypatch.setattr(
        "database.order.get_parent_orders",
        lambda: [root, child],
    )
    monkeypatch.setattr(
        "database.order.get_stealth_children_for_parent",
        lambda parent_order_id: (
            [stealth_child] if parent_order_id == ROOT_ID else []
        ),
    )
    monkeypatch.setattr(
        read_service,
        "evaluate_spot_follow_up_policy",
        lambda **_kwargs: SimpleNamespace(
            allowed=True,
            intent="exit",
            reason="allowed",
            product_type="SPOT",
        ),
    )

    submitted_chain = (
        read_service.AdminApiReadService().build_order_fill_follow_up_chain(
            client_order_id=ROOT_ID,
        )
    )

    assert submitted_chain.root_order is not None
    assert submitted_chain.root_order.client_order_id == ROOT_ID
    assert submitted_chain.root_order.status == "FILLED"
    assert submitted_chain.follow_up_child_client_order_ids == [CHILD_ID]
    assert submitted_chain.follow_up_child_count == 1
    submitted_child = submitted_chain.follow_up_children[0]
    assert submitted_child.client_order_id == CHILD_ID
    assert submitted_child.parent_client_order_id == ROOT_ID
    assert submitted_child.status == "OPEN"
    assert submitted_child.exchange_order_id == "exchange-child-1"
    assert submitted_child.last_lifecycle_event == (
        StealthLifecycleEvent.REVEAL_SUCCEEDED
    )
    assert submitted_chain.fill_follow_up_decision_audit is not None
    assert submitted_chain.fill_follow_up_decision_audit.claim_state == "done"
    assert submitted_chain.fill_follow_up_decision_audit.follow_up_decision == (
        "automatic_child_created"
    )

    child["status"] = "CANCELLED"
    stealth_child["stealth_status"] = "CANCELLED"
    stealth_child["last_lifecycle_event"] = (
        StealthLifecycleEvent.CANCELLED.value
    )

    reconciled_chain = (
        read_service.AdminApiReadService().build_order_fill_follow_up_chain(
            client_order_id=ROOT_ID,
        )
    )

    assert reconciled_chain.root_order is not None
    assert reconciled_chain.root_order.client_order_id == ROOT_ID
    assert reconciled_chain.root_order.status == "FILLED"
    assert reconciled_chain.follow_up_child_client_order_ids == [CHILD_ID]
    assert reconciled_chain.follow_up_child_count == 1
    visible_child = reconciled_chain.follow_up_children[0]
    assert visible_child.client_order_id == CHILD_ID
    assert visible_child.parent_client_order_id == ROOT_ID
    assert visible_child.status == "CANCELLED"
    assert visible_child.exchange_order_id == "exchange-child-1"
    assert visible_child.last_lifecycle_event == StealthLifecycleEvent.CANCELLED
    assert visible_child.ownership_provenance == (
        OrderOwnershipProvenance.ADMIN_FILL_FOLLOW_UP
    )
    assert reconciled_chain.fill_follow_up_decision_audit is not None
    assert reconciled_chain.fill_follow_up_decision_audit.claim_state == "done"
    assert reconciled_chain.fill_follow_up_decision_audit.claim_state_source == (
        "order_parent.durable_admin_fill_follow_up"
    )
    assert reconciled_chain.fill_follow_up_decision_audit.follow_up_decision == (
        "automatic_child_created"
    )
    assert not any(
        blocker.startswith("follow_up_child_missing_")
        for blocker in reconciled_chain.blockers
    )


def test_stealth_only_chain_child_preserves_source_and_withholds_raw_failure(
    monkeypatch,
) -> None:
    root = _filled_root(OrderOwnershipProvenance.ADMIN_MANUAL_ROOT.value)
    private_canary = "PRIVATE_COINBASE_EXCEPTION account=secret-account"
    stealth_child = {
        "stealth_order_id": CHILD_ID,
        "product_id": "BTC-USDC",
        "side": "SELL",
        "size": "0.01",
        "price": "160.00",
        "parent_order_id": ROOT_ID,
        "stealth_status": "HIDDEN",
        "last_lifecycle_event": StealthLifecycleEvent.REVEAL_FAILED.value,
        "failure_reason": private_canary,
    }
    monkeypatch.setattr(
        "database.order.get_parent_order",
        lambda client_order_id: root if client_order_id == ROOT_ID else None,
    )
    monkeypatch.setattr("database.order.get_parent_orders", lambda: [root])
    monkeypatch.setattr(
        "database.order.get_stealth_children_for_parent",
        lambda parent_order_id: (
            [stealth_child] if parent_order_id == ROOT_ID else []
        ),
    )

    chain = read_service.AdminApiReadService().build_order_fill_follow_up_chain(
        client_order_id=ROOT_ID,
    )
    payload = chain.model_dump(mode="json")

    assert payload["follow_up_child_count"] == 1
    assert payload["follow_up_children"][0]["source"] == "stealth_orders"
    assert payload["follow_up_children"][0]["failure_reason"] == "reveal_failed"
    assert private_canary not in json.dumps(payload, sort_keys=True)
