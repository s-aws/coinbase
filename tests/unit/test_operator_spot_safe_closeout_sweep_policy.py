from __future__ import annotations

from copy import deepcopy
import hashlib
import json

import pytest

from application.admin_api.operator_spot_safe_closeout_sweep_policy import (
    OperatorSpotSafeCloseoutSweepPolicyError,
    build_operator_spot_safe_closeout_sweep_plan,
)


PORTFOLIO_SHA256 = "a" * 64
RAW_EXCHANGE_ORDER_ID = "44444444-4444-4444-8444-444444444444"


def _candidate(index: int = 1) -> dict[str, object]:
    client_order_id = f"22222222-2222-4222-8222-{index:012d}"
    root_client_order_id = f"11111111-1111-4111-8111-{index:012d}"
    exchange_hash = hashlib.sha256(
        RAW_EXCHANGE_ORDER_ID.encode()
    ).hexdigest()
    payload = {
        "client_order_id": client_order_id,
        "root_client_order_id": root_client_order_id,
        "product_id": "BTC-USDC",
        "status": "OPEN",
        "ownership_provenance": "ADMIN_FILL_FOLLOW_UP",
        "portfolio_scope_sha256": PORTFOLIO_SHA256,
        "exchange_order_id_sha256": exchange_hash,
        "predecessor_evidence_sha256": "b" * 64,
        "created_at": "2026-07-27T00:00:00Z",
    }
    payload["candidate_evidence_sha256"] = hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    return payload


def test_builds_one_deterministic_cancel_only_plan_without_raw_exchange_id() -> None:
    first = build_operator_spot_safe_closeout_sweep_plan(
        candidates=[_candidate(1), _candidate(2)],
        configured_portfolio_scope_sha256=PORTFOLIO_SHA256,
    )
    second = build_operator_spot_safe_closeout_sweep_plan(
        candidates=[_candidate(1), _candidate(2)],
        configured_portfolio_scope_sha256=PORTFOLIO_SHA256,
    )

    assert first.sweep_id == second.sweep_id
    assert first.plan_sha256 == second.plan_sha256
    assert first.sweep_id == "73485d6b-2133-51ea-8ea0-fbf9e9c15acf"
    assert first.plan_sha256 == (
        "24f1f8534e5f29fec96d8c7247bad0e2197b8b67ab0b319e59b35194aa31a304"
    )
    assert [item.position for item in first.items] == [1, 2]
    persisted = first.to_persisted_payload()
    assert persisted["zero_creates"] is True
    assert RAW_EXCHANGE_ORDER_ID not in repr(persisted)
    assert "exchange_order_id" not in persisted
    assert first.plan_sha256 == hashlib.sha256(
        json.dumps(
            persisted,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


@pytest.mark.parametrize(
    ("mutator", "code"),
    [
        (
            lambda rows: rows + [_candidate(4)],
            "operator_spot_sweep_item_count_invalid",
        ),
        (
            lambda rows: [rows[0], deepcopy(rows[0])],
            "operator_spot_sweep_duplicate_candidate",
        ),
        (
            lambda rows: [
                {**rows[0], "status": "FILLED"},
            ],
            "operator_spot_sweep_candidate_not_active",
        ),
        (
            lambda rows: [
                {
                    **rows[0],
                    "ownership_provenance": "ADMIN_MANUAL_ROOT",
                },
            ],
            "operator_spot_sweep_candidate_not_system_child",
        ),
        (
            lambda rows: [
                {
                    **rows[0],
                    "portfolio_scope_sha256": "c" * 64,
                },
            ],
            "operator_spot_sweep_candidate_portfolio_mismatch",
        ),
    ],
)
def test_policy_fails_closed_on_unbounded_or_noncanonical_selection(
    mutator,
    code: str,
) -> None:
    rows = [_candidate(1), _candidate(2), _candidate(3)]

    with pytest.raises(
        OperatorSpotSafeCloseoutSweepPolicyError
    ) as exc:
        build_operator_spot_safe_closeout_sweep_plan(
            candidates=mutator(rows),
            configured_portfolio_scope_sha256=PORTFOLIO_SHA256,
        )

    assert exc.value.code == code
