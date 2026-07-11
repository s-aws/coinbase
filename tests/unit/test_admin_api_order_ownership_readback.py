from __future__ import annotations

from types import SimpleNamespace

from application.admin_api import read_service
from core.enums import OrderOwnershipProvenance, StealthLifecycleEvent


ROOT_ID = "880e8400-e29b-41d4-a716-446655440000"
CHILD_ID = "990e8400-e29b-41d4-a716-446655440000"
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
