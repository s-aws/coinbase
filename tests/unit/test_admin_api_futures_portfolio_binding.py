"""Focused tests for read-only Futures Default-profile binding evidence."""

from __future__ import annotations

import json

import pytest

from application.admin_api.futures_portfolio_binding import (
    evaluate_futures_default_portfolio_binding,
    serialize_public_futures_portfolio_binding,
)


DEFAULT_PORTFOLIO_ID = "11111111-2222-3333-4444-555555555555"
TEST_PORTFOLIO_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
OBSERVED_AT = "2026-07-13T12:00:00Z"


def permissions(
    *,
    portfolio_id: str | None = DEFAULT_PORTFOLIO_ID,
    portfolio_type: str | None = "DEFAULT",
    can_view: bool | None = True,
    can_trade: bool | None = True,
) -> dict[str, object]:
    return {
        "portfolio_uuid": portfolio_id,
        "portfolio_type": portfolio_type,
        "can_view": can_view,
        "can_trade": can_trade,
        "private_key": "must-never-be-returned",
    }


def portfolio_catalog(*rows: dict[str, object]) -> list[dict[str, object]]:
    return list(rows) or [
        {
            "uuid": TEST_PORTFOLIO_ID,
            "name": "Test",
            "type": "CONSUMER",
        },
        {
            "uuid": DEFAULT_PORTFOLIO_ID,
            "name": "Default",
            "type": "DEFAULT",
            "account_secret": "must-never-be-returned",
        },
    ]


def evaluate(
    *,
    permission_payload: object | None = None,
    portfolio_payload: object | None = None,
    permissions_read: bool = True,
    portfolio_catalog_read: bool = True,
    permissions_error: str | None = None,
    portfolio_catalog_error: str | None = None,
):
    return evaluate_futures_default_portfolio_binding(
        permissions=(
            permissions() if permission_payload is None else permission_payload
        ),
        portfolios=(
            portfolio_catalog() if portfolio_payload is None else portfolio_payload
        ),
        observed_at=OBSERVED_AT,
        permissions_read=permissions_read,
        portfolio_catalog_read=portfolio_catalog_read,
        permissions_error=permissions_error,
        portfolio_catalog_error=portfolio_catalog_error,
    )


def test_default_profile_read_binding_is_independent_from_trade_permission() -> None:
    evidence = evaluate(
        permission_payload=permissions(can_trade=False),
    )

    assert evidence.read_ready is True
    assert evidence.blocker is None
    assert evidence.can_view is True
    assert evidence.can_trade is False

    payload = evidence.to_dict()
    assert payload["status"] == "matched"
    assert payload["profile_alias"] == "Default"
    assert payload["portfolio_id"] == DEFAULT_PORTFOLIO_ID
    assert payload["observed_portfolio_type"] == "DEFAULT"
    assert payload["selection_authority"] == (
        "cdp_api_key_permissioned_portfolio"
    )
    assert payload["request_portfolio_override_allowed"] is False
    assert payload["credential_trade_permission_present"] is False
    assert payload["command_authority_granted"] is False
    assert payload["live_coinbase_execution_authorized"] is False


def test_default_profile_trade_permission_is_raw_evidence_without_command_authority() -> None:
    evidence = evaluate()

    assert evidence.read_ready is True
    assert evidence.can_trade is True
    assert evidence.to_dict()["credential_trade_permission_present"] is True
    assert evidence.to_dict()["command_authority_granted"] is False


@pytest.mark.parametrize(
    ("overrides", "expected_blocker"),
    [
        (
            {"permissions_read": False},
            "futures_default_portfolio_permissions_unavailable",
        ),
        (
            {"permissions_error": "credential reader failed: secret-value"},
            "futures_default_portfolio_permissions_unavailable",
        ),
        (
            {"permission_payload": permissions(portfolio_id=None)},
            "futures_default_permissioned_portfolio_missing",
        ),
        (
            {"permission_payload": permissions(portfolio_type="CONSUMER")},
            "futures_default_portfolio_type_mismatch",
        ),
        (
            {"portfolio_catalog_read": False},
            "futures_default_portfolio_catalog_unavailable",
        ),
        (
            {"portfolio_catalog_error": "catalog failed: secret-value"},
            "futures_default_portfolio_catalog_unavailable",
        ),
        (
            {
                "portfolio_payload": portfolio_catalog(
                    {
                        "uuid": TEST_PORTFOLIO_ID,
                        "name": "Test",
                        "type": "CONSUMER",
                    }
                )
            },
            "futures_default_permissioned_portfolio_missing",
        ),
        (
            {
                "portfolio_payload": portfolio_catalog(
                    {
                        "uuid": DEFAULT_PORTFOLIO_ID,
                        "name": "Default",
                        "type": "DEFAULT",
                    },
                    {
                        "uuid": DEFAULT_PORTFOLIO_ID,
                        "name": "Default",
                        "type": "DEFAULT",
                    },
                )
            },
            "futures_default_portfolio_catalog_ambiguous",
        ),
        (
            {
                "portfolio_payload": portfolio_catalog(
                    {
                        "uuid": DEFAULT_PORTFOLIO_ID,
                        "name": "Not Default",
                        "type": "DEFAULT",
                    }
                )
            },
            "futures_default_portfolio_label_mismatch",
        ),
        (
            {
                "portfolio_payload": portfolio_catalog(
                    {
                        "uuid": DEFAULT_PORTFOLIO_ID,
                        "name": "Default",
                        "type": "CONSUMER",
                    }
                )
            },
            "futures_default_portfolio_type_mismatch",
        ),
        (
            {"permission_payload": permissions(can_view=False)},
            "futures_default_portfolio_view_permission_missing",
        ),
    ],
)
def test_default_profile_binding_fails_closed_with_stable_blockers(
    overrides: dict[str, object],
    expected_blocker: str,
) -> None:
    evidence = evaluate(**overrides)

    assert evidence.read_ready is False
    assert evidence.blocker == expected_blocker
    assert evidence.to_dict()["status"] == "blocked"


def test_default_profile_binding_accepts_preloaded_sdk_shaped_evidence() -> None:
    class SdkEvidence:
        def __init__(self, payload: dict[str, object]) -> None:
            self.payload = payload

        def to_dict(self) -> dict[str, object]:
            return dict(self.payload)

    evidence = evaluate(
        permission_payload=SdkEvidence(permissions()),
        portfolio_payload={
            "portfolios": [
                SdkEvidence(
                    {
                        "uuid": DEFAULT_PORTFOLIO_ID,
                        "name": "Default",
                        "type": "DEFAULT",
                    }
                )
            ]
        },
    )

    assert evidence.read_ready is True
    assert evidence.observed_portfolio_id == DEFAULT_PORTFOLIO_ID


def test_default_profile_binding_dict_is_operator_safe() -> None:
    evidence = evaluate(
        permissions_error="credential reader failed: private-secret",
        portfolio_catalog_error="catalog reader failed: account-secret",
    )

    serialized = json.dumps(evidence.to_dict(), sort_keys=True)
    assert "private-secret" not in serialized
    assert "account-secret" not in serialized
    assert "must-never-be-returned" not in serialized
    assert evidence.to_dict()["permissions_error_present"] is True
    assert evidence.to_dict()["portfolio_catalog_error_present"] is True


def test_public_binding_projection_withholds_uuid_but_retains_internal_exact_id() -> None:
    evidence = evaluate()

    public = serialize_public_futures_portfolio_binding(evidence)

    assert evidence.observed_portfolio_id == DEFAULT_PORTFOLIO_ID
    assert evidence.to_dict()["portfolio_id"] == DEFAULT_PORTFOLIO_ID
    assert public["observed_portfolio_id"] is None
    assert public["portfolio_id"] is None
    assert public["portfolio_id_withheld"] is True
    assert public["status"] == "matched"
    assert public["profile_alias"] == "Default"
    assert public["can_view"] is True
    assert DEFAULT_PORTFOLIO_ID not in json.dumps(public, sort_keys=True)


def test_public_binding_projection_fails_closed_on_non_timestamp_observation() -> None:
    evidence = evaluate_futures_default_portfolio_binding(
        permissions=permissions(),
        portfolios=portfolio_catalog(),
        observed_at="withheld-reader-exception-text",
        permissions_read=True,
        portfolio_catalog_read=True,
    )

    assert evidence.read_ready is False
    assert evidence.blocker == "futures_default_portfolio_observed_at_missing"
    public = serialize_public_futures_portfolio_binding(evidence)

    assert public["status"] == "blocked"
    assert public["ready"] is False
    assert public["read_authorized"] is False
    assert public["blocker"] == "futures_default_portfolio_observed_at_missing"
    assert public["observed_at"] == "1970-01-01T00:00:00Z"
    assert "withheld-reader-exception-text" not in json.dumps(public, sort_keys=True)
