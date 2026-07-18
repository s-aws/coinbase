from __future__ import annotations

from types import SimpleNamespace

from core.operator_follow_up_intent import evaluate_operator_follow_up_intent_policy


def _known_spot(_product_id: str) -> dict[str, object]:
    return {
        "product_id": "BTC-USDC",
        "product_type": "SPOT",
        "catalog_found": True,
    }


def _allowed_policy(**_kwargs: object) -> SimpleNamespace:
    return SimpleNamespace(allowed=True, intent="exit")


def test_operator_follow_up_policy_rejects_unknown_catalog_product_even_if_spot_fallback():
    decision = evaluate_operator_follow_up_intent_policy(
        source_status="OPEN",
        source_ownership_provenance="ADMIN_MANUAL_ROOT",
        source_portfolio_matches=True,
        root_lineage_valid=True,
        product_id="UNKNOWN-XYZ",
        source_side="BUY",
        product_context_resolver=lambda _product_id: {
            "product_id": "UNKNOWN-XYZ",
            "product_type": "SPOT",
            "catalog_found": False,
        },
        spot_policy_evaluator=_allowed_policy,
    )

    assert decision.allowed is False
    assert decision.product_type == "UNKNOWN"
    assert "source_product_unknown" in decision.blockers
    assert decision.semantic_intent is None


def test_operator_follow_up_policy_derives_exact_known_spot_exit():
    decision = evaluate_operator_follow_up_intent_policy(
        source_status="OPEN",
        source_ownership_provenance="ADMIN_MANUAL_ROOT",
        source_portfolio_matches=True,
        root_lineage_valid=True,
        product_id="BTC-USDC",
        source_side="BUY",
        product_context_resolver=_known_spot,
        spot_policy_evaluator=_allowed_policy,
    )

    assert decision.allowed is True
    assert decision.blockers == ()
    assert decision.product_type == "SPOT"
    assert decision.derived_follow_up_side == "SELL"
    assert decision.semantic_intent == "EXIT"


def test_operator_follow_up_policy_fails_closed_for_non_open_or_untraced_source():
    decision = evaluate_operator_follow_up_intent_policy(
        source_status="PENDING",
        source_ownership_provenance="EXTERNAL",
        source_portfolio_matches=False,
        root_lineage_valid=False,
        product_id="BTC-USDC",
        source_side="BUY",
        product_context_resolver=_known_spot,
        spot_policy_evaluator=_allowed_policy,
    )

    assert decision.allowed is False
    assert decision.blockers == (
        "source_status_not_open",
        "source_not_system_owned",
        "source_portfolio_scope_mismatch",
        "source_root_lineage_invalid",
    )
