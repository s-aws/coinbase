from __future__ import annotations

import hashlib
import json
from uuid import UUID

import pytest
from pydantic import ValidationError

from application.admin_api.operator_single_order_reprice_now_models import (
    OperatorSingleOrderRepriceNowIntentPlan,
)
from application.admin_api.operator_single_order_reprice_now_policy import (
    OperatorSingleOrderRepriceNowPolicyError,
    build_single_order_reprice_now_intent,
)


STEALTH_ID = "11111111-1111-4111-8111-111111111111"
SOURCE_CLIENT_ORDER_ID = "22222222-2222-4222-8222-222222222222"
DEFINITION_SHA256 = "a" * 64
SOURCE_EVIDENCE_SHA256 = "b" * 64


def _source() -> dict[str, object]:
    return {
        "stealth_order_id": STEALTH_ID,
        "source_client_order_id": SOURCE_CLIENT_ORDER_ID,
        "definition_revision": 7,
        "definition_sha256": DEFINITION_SHA256,
        "source_evidence_sha256": SOURCE_EVIDENCE_SHA256,
        "root_client_order_id": STEALTH_ID,
        "source_status": "REVEALED",
        "zero_fill_proven": True,
        "system_owned": True,
        "direct_parent": True,
    }


def test_builds_deterministic_non_market_intent() -> None:
    first = build_single_order_reprice_now_intent(source=_source())
    second = build_single_order_reprice_now_intent(source=_source())

    assert first.reserved_successor_client_order_id == (
        second.reserved_successor_client_order_id
    )
    assert UUID(first.reserved_successor_client_order_id).version == 5
    assert first.intent_sha256 == second.intent_sha256
    payload = first.to_persisted_payload()
    assert set(payload) == {
        "goal_id",
        "policy_revision",
        "stealth_order_id",
        "source_client_order_id",
        "reserved_successor_client_order_id",
        "root_client_order_id",
        "definition_revision",
        "definition_sha256",
        "source_evidence_sha256",
        "source_status",
        "zero_fill_proven",
        "system_owned",
        "direct_parent",
    }
    assert not {
        "product_id",
        "portfolio_id",
        "portfolio_scope_sha256",
        "price",
        "size",
        "submitted_notional",
        "possible_execution_notional",
        "cap",
    }.intersection(payload)
    assert first.intent_sha256 == hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    OperatorSingleOrderRepriceNowIntentPlan(**payload)


def test_contract_rejects_non_v5_reserved_successor() -> None:
    intent = build_single_order_reprice_now_intent(source=_source())
    payload = intent.to_persisted_payload()
    payload["reserved_successor_client_order_id"] = (
        "33333333-3333-4333-8333-333333333333"
    )

    with pytest.raises(ValidationError):
        OperatorSingleOrderRepriceNowIntentPlan(**payload)


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        (
            "source_status",
            "HIDDEN",
            "operator_reprice_now_source_not_revealed",
        ),
        (
            "zero_fill_proven",
            False,
            "operator_reprice_now_zero_fill_not_proven",
        ),
        (
            "system_owned",
            False,
            "operator_reprice_now_source_not_system_owned",
        ),
        (
            "direct_parent",
            False,
            "operator_reprice_now_source_not_direct_parent",
        ),
        (
            "root_client_order_id",
            SOURCE_CLIENT_ORDER_ID,
            "operator_reprice_now_source_not_direct_parent",
        ),
    ],
)
def test_fails_closed_on_noncanonical_source(
    field: str,
    value: object,
    code: str,
) -> None:
    source = _source()
    source[field] = value

    with pytest.raises(OperatorSingleOrderRepriceNowPolicyError) as exc:
        build_single_order_reprice_now_intent(source=source)

    assert exc.value.code == code
