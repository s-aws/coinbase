from __future__ import annotations

from dataclasses import replace
import hashlib
import json

import pytest

from application.admin_api.operator_parent_move_premark_policy import (
    ParentMovePremarkPolicyError,
    ParentMovePremarkPolicyTerms,
    build_parent_move_premark_plan,
)


SOURCE_ID = "11111111-1111-4111-8111-111111111111"
SUCCESSOR_ID = "22222222-2222-4222-8222-222222222222"
PORTFOLIO_SHA256 = "a" * 64


def _source(**overrides: object) -> dict[str, object]:
    source: dict[str, object] = {
        "client_order_id": SOURCE_ID,
        "parent_order_id": None,
        "ownership_provenance": "ADMIN_MANUAL_ROOT",
        "portfolio_scope_sha256": PORTFOLIO_SHA256,
        "product_id": "BTC-USDC",
        "side": "BUY",
        "size": "0.001",
        "limit_price": "900",
        "filled_size": "0",
        "status": "OPEN",
        "order_type": "LIMIT",
        "time_in_force": "GOOD_UNTIL_CANCELLED",
        "authoritatively_nonterminal": True,
        "cancel_eligible": True,
        "post_only_compatible": True,
    }
    source.update(overrides)
    return source


def _terms(**overrides: object) -> ParentMovePremarkPolicyTerms:
    values: dict[str, object] = {
        "terms_complete": True,
        "policy_revision": "PARENT_MOVE_PREMARK_V1",
        "portfolio_scope_sha256": PORTFOLIO_SHA256,
        "approved_product_id": "BTC-USDC",
        "price_increment": "0.01",
        "base_increment": "0.00000001",
        "base_min_size": "0.00000001",
        "quote_min_size": "0.01",
        "max_submitted_notional_usdc": "3.10",
        "max_possible_execution_notional_usdc": "1.00",
    }
    values.update(overrides)
    return ParentMovePremarkPolicyTerms(**values)


def test_default_terms_fail_closed_before_a_plan_exists() -> None:
    with pytest.raises(ParentMovePremarkPolicyError) as exc_info:
        build_parent_move_premark_plan(
            source=_source(),
            requested_limit_price="901.239",
            reserved_successor_client_order_id=SUCCESSOR_ID,
            policy_terms=ParentMovePremarkPolicyTerms(),
            legacy_pending_move=False,
        )

    assert exc_info.value.code == (
        "operator_parent_move_authority_terms_incomplete"
    )


def test_builds_immutable_same_order_terms_with_maker_safe_quantization() -> None:
    plan = build_parent_move_premark_plan(
        source=_source(),
        requested_limit_price="901.239",
        reserved_successor_client_order_id=SUCCESSOR_ID,
        policy_terms=_terms(),
        legacy_pending_move=False,
    )

    assert plan.goal_id == "operator_parent_move_premark_lifecycle_v1"
    assert plan.source_client_order_id == SOURCE_ID
    assert plan.successor_client_order_id == SUCCESSOR_ID
    assert plan.product_id == "BTC-USDC"
    assert plan.side == "BUY"
    assert plan.size == "0.001"
    assert plan.requested_limit_price == "901.239"
    assert plan.successor_limit_price == "901.23"
    assert plan.submitted_notional_usdc == "0.90123"
    assert plan.possible_execution_notional_usdc == "0.90123"
    assert plan.portfolio_scope_sha256 == PORTFOLIO_SHA256
    assert len(plan.source_evidence_sha256) == 64
    assert len(plan.plan_sha256) == 64
    assert not hasattr(plan, "exchange_order_id")
    assert plan.to_persisted_payload()["source_client_order_id"] == SOURCE_ID
    assert "plan_sha256" not in plan.to_persisted_payload()
    assert plan.plan_sha256 == hashlib.sha256(
        json.dumps(
            plan.to_persisted_payload(),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


@pytest.mark.parametrize(
    ("override", "expected"),
    [
        ({"client_order_id": "not-a-uuid"}, "identity_invalid"),
        (
            {
                "client_order_id": (
                    "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA"
                )
            },
            "identity_invalid",
        ),
        ({"parent_order_id": SUCCESSOR_ID}, "not_direct_root"),
        ({"ownership_provenance": "EXTERNAL_WS_OBSERVED"}, "not_system_owned"),
        ({"filled_size": "0.0001"}, "not_zero_fill"),
        ({"status": "FILLED"}, "terminal"),
        (
            {"authoritatively_nonterminal": False},
            "not_authoritatively_nonterminal",
        ),
        ({"cancel_eligible": False}, "not_cancel_eligible"),
        ({"order_type": "MARKET"}, "configuration_invalid"),
        ({"time_in_force": "IMMEDIATE_OR_CANCEL"}, "configuration_invalid"),
        ({"post_only_compatible": False}, "configuration_invalid"),
        ({"portfolio_scope_sha256": "b" * 64}, "portfolio_scope_mismatch"),
        ({"product_id": "ETH-USDC"}, "product_not_approved"),
    ],
)
def test_rejects_sources_without_exact_direct_root_authority(
    override: dict[str, object],
    expected: str,
) -> None:
    with pytest.raises(ParentMovePremarkPolicyError) as exc_info:
        build_parent_move_premark_plan(
            source=_source(**override),
            requested_limit_price="901.23",
            reserved_successor_client_order_id=SUCCESSOR_ID,
            policy_terms=_terms(),
            legacy_pending_move=False,
        )

    assert exc_info.value.code == f"operator_parent_move_source_{expected}"


def test_rejects_legacy_pending_move_without_creating_parallel_authority() -> None:
    with pytest.raises(ParentMovePremarkPolicyError) as exc_info:
        build_parent_move_premark_plan(
            source=_source(),
            requested_limit_price="901.23",
            reserved_successor_client_order_id=SUCCESSOR_ID,
            policy_terms=_terms(),
            legacy_pending_move=True,
        )

    assert exc_info.value.code == "operator_parent_move_legacy_pending"


def test_rejects_cap_or_incomplete_policy_evidence() -> None:
    with pytest.raises(ParentMovePremarkPolicyError) as cap_error:
        build_parent_move_premark_plan(
            source=_source(size="0.002"),
            requested_limit_price="901.23",
            reserved_successor_client_order_id=SUCCESSOR_ID,
            policy_terms=_terms(),
            legacy_pending_move=False,
        )
    assert cap_error.value.code == "operator_parent_move_cap_exceeded"

    incomplete_hash = replace(
        _terms(),
        portfolio_scope_sha256=None,
    )
    with pytest.raises(ParentMovePremarkPolicyError) as terms_error:
        build_parent_move_premark_plan(
            source=_source(),
            requested_limit_price="901.23",
            reserved_successor_client_order_id=SUCCESSOR_ID,
            policy_terms=incomplete_hash,
            legacy_pending_move=False,
        )
    assert terms_error.value.code == (
        "operator_parent_move_authority_terms_incomplete"
    )
