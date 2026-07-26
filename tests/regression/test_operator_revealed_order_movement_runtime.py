from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

import pytest

from application.admin_api.command_service import (
    coinbase_order_readback_zero_fill_classification,
)
from core.enums import StealthMoveReason
from core.models import RevealExecutionPlan, StealthMovePlan


STEALTH_ID = "11111111-1111-4111-8111-111111111111"
SOURCE_CLIENT_ID = "22222222-2222-4222-8222-222222222222"
REPLACEMENT_CLIENT_ID = "33333333-3333-4333-8333-333333333333"
PORTFOLIO_ID = "44444444-4444-4444-8444-444444444444"
REVISION_ID = "55555555-5555-4555-8555-555555555555"
RAW_SOURCE_EXCHANGE_ID = "raw-source-exchange-id"


@pytest.mark.parametrize(
    ("matched_order", "expected"),
    [
        ({"filled_size": "0"}, "ZERO"),
        ({"filled_size": "0", "number_of_fills": "1"}, "NONZERO"),
        ({"filled_size": "0.00000001"}, "NONZERO"),
        ({"filled_size": "-0.00000001"}, "UNKNOWN"),
        ({"status": "OPEN"}, "UNKNOWN"),
        ({"filled_size": "withheld-malformed"}, "UNKNOWN"),
    ],
)
def test_zero_fill_classification_is_value_blind_and_fail_closed(
    matched_order: dict[str, Any],
    expected: str,
) -> None:
    assert (
        coinbase_order_readback_zero_fill_classification(
            {"matched_order": matched_order}
        )
        == expected
    )


def _portfolio_hash() -> str:
    return hashlib.sha256(PORTFOLIO_ID.encode()).hexdigest()


def _definition() -> dict[str, Any]:
    return {
        "definition_id": STEALTH_ID,
        "revision": 4,
        "definition_sha256": "a" * 64,
        "portfolio_scope_sha256": _portfolio_hash(),
        "admitted_product_catalog_revision_id": REVISION_ID,
        "admitted_product_catalog_snapshot_sha256": "b" * 64,
        "product_id": "BTC-USDC",
        "side": "BUY",
        "target_movement": "0.01",
        "target_movement_type": "P",
    }


@dataclass
class _Catalog:
    active_revision_id: str = REVISION_ID

    def get_active_revision_id(self) -> str:
        return self.active_revision_id

    def get_revision(self, revision_id: str) -> dict[str, Any]:
        assert revision_id == REVISION_ID
        return {
            "revision_id": REVISION_ID,
            "snapshot_sha256": "b" * 64,
            "active": True,
        }

    def list_revision_products(self, revision_id: str) -> list[dict[str, Any]]:
        assert revision_id == REVISION_ID
        return [
            {
                "product_id": "BTC-USDC",
                "product_type": "SPOT",
                "lifecycle": "ENABLED",
                "exchange_status": "ONLINE",
                "exchange_disabled": False,
                "cancel_only": False,
                "view_only": False,
                "price_increment": "0.01",
                "base_increment": "0.00000001",
                "base_min_size": "0.00000001",
                "base_max_size": "10",
                "quote_min_size": "0.01",
                "quote_max_size": "1000000",
            }
        ]


@dataclass
class _Manager:
    cancel_result: bool = True
    allow_partial_fills: bool = False
    source_placement_size: str = "0.00001"
    source_placement_status: str = "OPEN"
    source_placement_exchange_id: str = RAW_SOURCE_EXCHANGE_ID
    create_result: dict[str, Any] = field(
        default_factory=lambda: {
            "outcome": "ACCEPTED",
            "exchange_order_id": "raw-replacement-exchange-id",
        }
    )
    calls: list[str] = field(default_factory=list)

    expected_retail_portfolio_id: str = PORTFOLIO_ID

    def _get_stealth_order(self, stealth_order_id: str) -> dict[str, Any]:
        assert stealth_order_id == STEALTH_ID
        return {
            "stealth_order_id": STEALTH_ID,
            "product_id": "BTC-USDC",
            "side": "BUY",
            "status": "REVEALED",
            "executed_size": 0,
            "remaining_size": 0,
            "total_size": 0.00001,
            "limit_price": 50000,
            "target_movement": 0.01,
            "target_movement_type": "P",
            "allow_partial_fills": self.allow_partial_fills,
            "parent_order_id": STEALTH_ID,
            "anchor_repricing_state_json": {
                "active_placement_client_order_id": SOURCE_CLIENT_ID,
                "active_exchange_order_id": RAW_SOURCE_EXCHANGE_ID,
                "active_exchange_price": 50000,
            },
        }

    def get_operator_stealth_move_source_placement(
        self,
        stealth_order_id: str,
    ) -> dict[str, Any]:
        assert stealth_order_id == STEALTH_ID
        return {
            "client_order_id": SOURCE_CLIENT_ID,
            "product_id": "BTC-USDC",
            "side": "BUY",
            "size": self.source_placement_size,
            "price": "50000",
            "status": self.source_placement_status,
            "parent_order_id": STEALTH_ID,
            "retail_portfolio_id": PORTFOLIO_ID,
            "exchange_order_id": self.source_placement_exchange_id,
            "allow_partial_fills": False,
        }

    def build_operator_stealth_move_plan(
        self,
        stealth_order_id: str,
        new_limit_price: float,
        **_: Any,
    ) -> StealthMovePlan:
        self.calls.append("build_operator_stealth_move_plan")
        assert stealth_order_id == STEALTH_ID
        assert new_limit_price == 50000.12
        return StealthMovePlan(
            stealth_order_id=STEALTH_ID,
            root_parent_client_order_id=STEALTH_ID,
            old_exchange_order_id=RAW_SOURCE_EXCHANGE_ID,
            old_submitted_price=50000,
            new_configured_limit_price=50000.12,
            reveal_plan=RevealExecutionPlan(
                configured_limit_price=50000.12,
                submitted_limit_price=50000.12,
                reveal_pricing_policy="configured_limit",
                reveal_price_source="configured_limit",
                fallback_used=False,
                market_source="operator",
                market_bid=50000,
                market_ask=50001,
                target_movement=0.01,
                target_movement_type="P",
                target_movement_source="operator_definition",
                post_only=True,
            ),
            reason=StealthMoveReason.MANUAL_USER_MOVE,
        )

    def validate_operator_stealth_move_profitability(
        self, **_: Any
    ) -> bool:
        self.calls.append("validate_profitability")
        return True

    def cancel_operator_stealth_move(
        self,
        *,
        authority: dict[str, Any],
        before_cancel_call,
    ) -> bool:
        self.calls.append("cancel_operator_stealth_move")
        assert authority.replacement_client_order_id == REPLACEMENT_CLIENT_ID
        before_cancel_call()
        return self.cancel_result

    def place_operator_stealth_move_replacement(
        self,
        *,
        authority: dict[str, Any],
        before_create_call,
        before_wallet_read,
        after_wallet_read,
    ) -> dict[str, Any]:
        self.calls.append("place_operator_stealth_move_replacement")
        assert authority.replacement_client_order_id == REPLACEMENT_CLIENT_ID
        before_wallet_read()
        after_wallet_read("RETURNED")
        before_create_call()
        return dict(self.create_result)

    def complete_operator_stealth_move_reconciliation(
        self,
        *,
        authority: dict[str, Any],
        replacement_exchange_order_id: str,
    ) -> None:
        self.calls.append("complete_operator_stealth_move_reconciliation")
        assert authority.replacement_client_order_id == REPLACEMENT_CLIENT_ID
        assert replacement_exchange_order_id == (
            "raw-replacement-exchange-id"
        )


@dataclass
class _RestClient:
    statuses: list[str]


def _runtime(manager: _Manager, rest: _RestClient):
    from application.admin_api.operator_revealed_order_movement_runtime import (
        OperatorRevealedOrderMovementRuntime,
    )

    return OperatorRevealedOrderMovementRuntime(
        manager=manager,
        rest_client=rest,
        product_catalog_repository=_Catalog(),
        configured_portfolio_id=PORTFOLIO_ID,
        replacement_client_order_id_factory=lambda: REPLACEMENT_CLIENT_ID,
    )


def test_build_plan_quantizes_and_withholds_exchange_identity() -> None:
    manager = _Manager()
    plan = _runtime(manager, _RestClient([])).build_plan(
        _definition(),
        requested_limit_price="50000.127",
    )

    assert plan["replacement_limit_price"] == "50000.12"
    assert plan["replacement_client_order_id"] == REPLACEMENT_CLIENT_ID
    assert plan["source_client_order_id"] == SOURCE_CLIENT_ID
    assert plan["source_exchange_order_id_sha256"] == hashlib.sha256(
        RAW_SOURCE_EXCHANGE_ID.encode()
    ).hexdigest()
    assert RAW_SOURCE_EXCHANGE_ID not in str(plan)
    assert plan["post_only"] is True
    assert plan["zero_fill_validated"] is True
    assert plan["profitability_validated"] is True
    assert manager.calls == [
        "build_operator_stealth_move_plan",
        "validate_profitability",
    ]


def test_build_plan_uses_canonical_active_placement_size_after_reveal() -> None:
    manager = _Manager(source_placement_size="0.00001234")
    plan = _runtime(manager, _RestClient([])).build_plan(
        _definition(),
        requested_limit_price="50000.127",
    )

    assert plan["base_size"] == "0.00001234"
    assert plan["base_size"] != str(
        manager._get_stealth_order(STEALTH_ID)["remaining_size"]
    )


def test_build_plan_accepts_goal6_withheld_parent_exchange_identity() -> None:
    plan = _runtime(
        _Manager(source_placement_exchange_id=""),
        _RestClient([]),
    ).build_plan(
        _definition(),
        requested_limit_price="50000.127",
    )

    assert plan["source_exchange_order_id_sha256"] == hashlib.sha256(
        RAW_SOURCE_EXCHANGE_ID.encode()
    ).hexdigest()
    assert RAW_SOURCE_EXCHANGE_ID not in str(plan)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_placement_size", "0"),
        ("source_placement_status", "FILLED"),
        ("source_placement_exchange_id", "different-exchange-order"),
    ],
)
def test_build_plan_rejects_noncanonical_active_placement(
    field: str,
    value: str,
) -> None:
    manager = _Manager()
    setattr(manager, field, value)

    with pytest.raises(
        RuntimeError,
        match="operator_move_zero_fill_not_proven",
    ):
        _runtime(manager, _RestClient([])).build_plan(
            _definition(),
            requested_limit_price="50000.127",
        )


def test_build_plan_rejects_stale_catalog_binding() -> None:
    definition = _definition()
    definition["admitted_product_catalog_snapshot_sha256"] = "9" * 64

    with pytest.raises(
        RuntimeError,
        match="operator_move_product_catalog_binding_invalid",
    ):
        _runtime(_Manager(), _RestClient([])).build_plan(
            definition,
            requested_limit_price="50000.127",
        )


def test_build_plan_rejects_target_identity_drift() -> None:
    definition = _definition()
    definition["target_movement"] = "0.02"

    with pytest.raises(
        RuntimeError,
        match="operator_move_zero_fill_not_proven",
    ):
        _runtime(_Manager(), _RestClient([])).build_plan(
            definition,
            requested_limit_price="50000.127",
        )


def test_build_plan_rejects_partial_fill_enabled_source() -> None:
    with pytest.raises(
        RuntimeError,
        match="operator_move_zero_fill_not_proven",
    ):
        _runtime(
            _Manager(allow_partial_fills=True),
            _RestClient([]),
        ).build_plan(
            _definition(),
            requested_limit_price="50000.127",
        )


def test_cancel_requires_exact_open_then_exact_cancelled_readback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _Manager()
    rest = _RestClient(["OPEN", "CANCELLED"])
    read_claims: list[str] = []
    read_results: list[str] = []
    cancel_claims: list[str] = []

    monkeypatch.setattr(
        "application.admin_api.operator_revealed_order_movement_runtime."
        "_exact_readback",
        lambda **kwargs: (
            kwargs["before_call"](),
            {
                "status": kwargs["rest_client"].statuses.pop(0),
                "authoritative": True,
                "zero_fill_classification": "ZERO",
                "terms_proven": True,
            },
        )[1],
    )
    monkeypatch.setattr(
        "application.admin_api.operator_revealed_order_movement_runtime."
        "require_coinbase_execution_authority",
        lambda **_: None,
    )
    outcome = _runtime(manager, rest).cancel_source(
        _runtime(manager, rest).build_plan(
            _definition(),
            requested_limit_price="50000.127",
        ),
        before_pre_cancel_read=lambda: read_claims.append("pre"),
        after_pre_cancel_read=lambda value: read_results.append(value),
        before_cancel_call=lambda: cancel_claims.append("cancel"),
        before_post_cancel_read=lambda: read_claims.append("post"),
        after_post_cancel_read=lambda value: read_results.append(value),
    )

    assert outcome == "CANCELLED"
    assert read_claims == ["pre", "post"]
    assert read_results == ["OPEN", "CANCELLED"]
    assert cancel_claims == ["cancel"]
    assert manager.calls[-1] == "cancel_operator_stealth_move"


def test_pre_cancel_nonzero_fill_proof_prohibits_cancel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _Manager()
    rest = _RestClient(["OPEN"])
    cancel_claims: list[str] = []

    monkeypatch.setattr(
        "application.admin_api.operator_revealed_order_movement_runtime."
        "_exact_readback",
        lambda **kwargs: (
            kwargs["before_call"](),
            {
                "status": kwargs["rest_client"].statuses.pop(0),
                "authoritative": True,
                "zero_fill_classification": "NONZERO",
                "terms_proven": None,
            },
        )[1],
    )
    runtime = _runtime(manager, rest)
    outcome = runtime.cancel_source(
        runtime.build_plan(
            _definition(),
            requested_limit_price="50000.127",
        ),
        before_pre_cancel_read=lambda: None,
        after_pre_cancel_read=lambda _: None,
        before_cancel_call=lambda: cancel_claims.append("cancel"),
        before_post_cancel_read=lambda: None,
        after_post_cancel_read=lambda _: None,
    )

    assert outcome == "FILLED"
    assert cancel_claims == []
    assert "cancel_operator_stealth_move" not in manager.calls


def test_cancel_post_read_fill_is_unknown_after_cancel_allowance_consumed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _Manager()
    rest = _RestClient(["OPEN", "CANCELLED"])

    monkeypatch.setattr(
        "application.admin_api.operator_revealed_order_movement_runtime."
        "_exact_readback",
        lambda **kwargs: (
            kwargs["before_call"](),
            {
                "status": kwargs["rest_client"].statuses.pop(0),
                "authoritative": True,
                "zero_fill_classification": (
                    "ZERO" if kwargs["rest_client"].statuses else "NONZERO"
                ),
                "terms_proven": None,
            },
        )[1],
    )
    monkeypatch.setattr(
        "application.admin_api.operator_revealed_order_movement_runtime."
        "require_coinbase_execution_authority",
        lambda **_: None,
    )

    outcome = _runtime(manager, rest).cancel_source(
        _runtime(manager, rest).build_plan(
            _definition(),
            requested_limit_price="50000.127",
        ),
        before_pre_cancel_read=lambda: None,
        after_pre_cancel_read=lambda _: None,
        before_cancel_call=lambda: None,
        before_post_cancel_read=lambda: None,
        after_post_cancel_read=lambda _: None,
    )

    assert outcome == "UNKNOWN"


def test_pre_cancel_read_failure_before_claim_is_fixed_unclaimed_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _Manager()
    rest = _RestClient([])
    read_claims: list[str] = []
    read_results: list[str] = []
    cancel_claims: list[str] = []

    monkeypatch.setattr(
        "application.admin_api.operator_revealed_order_movement_runtime."
        "_exact_readback",
        lambda **_: (_ for _ in ()).throw(
            RuntimeError("withheld-before-call")
        ),
    )

    outcome = _runtime(manager, rest).cancel_source(
        _runtime(manager, rest).build_plan(
            _definition(),
            requested_limit_price="50000.127",
        ),
        before_pre_cancel_read=lambda: read_claims.append("pre"),
        after_pre_cancel_read=lambda value: read_results.append(value),
        before_cancel_call=lambda: cancel_claims.append("cancel"),
        before_post_cancel_read=lambda: read_claims.append("post"),
        after_post_cancel_read=lambda value: read_results.append(value),
    )

    assert outcome == "PRE_CANCEL_UNKNOWN"
    assert read_claims == []
    assert read_results == []
    assert cancel_claims == []
    assert "withheld-before-call" not in str(manager.calls)


def test_create_hashes_identity_and_reconciles_exact_replacement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _Manager()
    rest = _RestClient(["OPEN"])
    claims: list[str] = []
    reads: list[str] = []
    monkeypatch.setattr(
        "application.admin_api.operator_revealed_order_movement_runtime."
        "_exact_readback",
        lambda **kwargs: (
            kwargs["before_call"](),
            {
                "status": kwargs["rest_client"].statuses.pop(0),
                "authoritative": True,
                "zero_fill_classification": "ZERO",
                "terms_proven": True,
            },
        )[1],
    )
    monkeypatch.setattr(
        "application.admin_api.operator_revealed_order_movement_runtime."
        "require_coinbase_execution_authority",
        lambda **_: None,
    )
    plan = _runtime(manager, rest).build_plan(
        _definition(),
        requested_limit_price="50000.127",
    )
    result = _runtime(manager, rest).create_replacement(
        plan,
        before_create_call=lambda: claims.append("create"),
        before_wallet_read=lambda: reads.append("wallet-claim"),
        after_wallet_read=lambda value: reads.append(value),
        before_post_create_read=lambda: reads.append("claim"),
        after_post_create_read=lambda value: reads.append(value),
    )

    assert result["outcome"] == "ACCEPTED"
    assert result["replacement_exchange_order_id_sha256"] == hashlib.sha256(
        b"raw-replacement-exchange-id"
    ).hexdigest()
    assert "raw-replacement-exchange-id" not in str(result)
    assert claims == ["create"]
    assert reads == ["wallet-claim", "RETURNED", "claim", "OPEN"]
    assert manager.calls[-1] == (
        "complete_operator_stealth_move_reconciliation"
    )


def test_create_unknown_readback_keeps_reconciliation_fence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _Manager()
    rest = _RestClient(["UNKNOWN"])
    monkeypatch.setattr(
        "application.admin_api.operator_revealed_order_movement_runtime."
        "_exact_readback",
        lambda **kwargs: (
            kwargs["before_call"](),
            {
                "status": kwargs["rest_client"].statuses.pop(0),
                "authoritative": True,
                "zero_fill_classification": "ZERO",
                "terms_proven": True,
            },
        )[1],
    )
    monkeypatch.setattr(
        "application.admin_api.operator_revealed_order_movement_runtime."
        "require_coinbase_execution_authority",
        lambda **_: None,
    )
    runtime = _runtime(manager, rest)
    result = runtime.create_replacement(
        runtime.build_plan(
            _definition(),
            requested_limit_price="50000.127",
        ),
        before_create_call=lambda: None,
        before_wallet_read=lambda: None,
        after_wallet_read=lambda _: None,
        before_post_create_read=lambda: None,
        after_post_create_read=lambda _: None,
    )

    assert result["outcome"] == "UNKNOWN"
    assert "complete_operator_stealth_move_reconciliation" not in (
        manager.calls
    )


def test_create_readback_must_prove_identical_replacement_terms(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _Manager()
    rest = _RestClient(["OPEN"])
    monkeypatch.setattr(
        "application.admin_api.operator_revealed_order_movement_runtime."
        "_exact_readback",
        lambda **kwargs: (
            kwargs["before_call"](),
            {
                "status": kwargs["rest_client"].statuses.pop(0),
                "authoritative": True,
                "zero_fill_classification": "ZERO",
                "terms_proven": False,
            },
        )[1],
    )
    monkeypatch.setattr(
        "application.admin_api.operator_revealed_order_movement_runtime."
        "require_coinbase_execution_authority",
        lambda **_: None,
    )
    runtime = _runtime(manager, rest)
    result = runtime.create_replacement(
        runtime.build_plan(
            _definition(),
            requested_limit_price="50000.127",
        ),
        before_create_call=lambda: None,
        before_wallet_read=lambda: None,
        after_wallet_read=lambda _: None,
        before_post_create_read=lambda: None,
        after_post_create_read=lambda _: None,
    )

    assert result == {
        "outcome": "UNKNOWN",
        "replacement_exchange_order_id_sha256": None,
    }
    assert "complete_operator_stealth_move_reconciliation" not in manager.calls
