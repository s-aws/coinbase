from __future__ import annotations

import json
from typing import Any

import pytest

import api.v1.routes.futures as futures_routes
from application.admin_api.models import (
    AdminFuturesOrderPreviewR12Response,
    AdminFuturesPreviewR12PostStageEvidenceRow,
)


class _R12ReadStore:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.path = "/tmp/synthetic-r12-artifact.jsonl"
        self._payload = payload

    def read_completed(self) -> dict[str, Any]:
        return dict(self._payload)


@pytest.mark.parametrize(
    ("stage", "reason_code"),
    [
        (
            "preview_response_validation",
            "futures_preview_response_official_response_missing",
        ),
        (
            "candidate_cap_binding",
            "futures_preview_response_validation_blocked",
        ),
    ],
)
def test_r12_post_stage_contract_rejects_internal_or_mismatched_reasons(
    stage: str,
    reason_code: str,
) -> None:
    with pytest.raises(ValueError):
        AdminFuturesPreviewR12PostStageEvidenceRow.model_validate(
            {
                "stage": stage,
                "status": "blocked",
                "reason_code": reason_code,
            }
        )


def test_r12_json_schema_enumerates_strict_nested_evidence_contracts() -> None:
    schema = AdminFuturesOrderPreviewR12Response.model_json_schema()

    assert {
        "preview_response",
        "preview_response_sha256",
        "preview_id_sha256",
        "post_preview_stage_evidence_sha256",
    } <= set(schema["required"])

    def resolve(node: dict[str, Any]) -> dict[str, Any]:
        reference = node.get("$ref")
        assert isinstance(reference, str)
        return schema["$defs"][reference.rsplit("/", 1)[-1]]

    eligibility = resolve(schema["properties"]["non_attempt_eligibility"])
    assert eligibility["additionalProperties"] is False
    assert {
        "portfolio_binding",
        "permission_evidence",
        "portfolio_catalog_evidence",
        "product_evidence",
        "market_evidence",
        "position_evidence",
        "margin_collateral_evidence",
        "margin_window_policy_evidence",
        "transport_policy_evidence",
        "candidate",
        "preview_request",
    } <= set(eligibility["properties"])
    for field in (
        "portfolio_binding",
        "permission_evidence",
        "portfolio_catalog_evidence",
        "product_evidence",
        "market_evidence",
        "position_evidence",
        "margin_collateral_evidence",
        "margin_window_policy_evidence",
        "transport_policy_evidence",
        "candidate",
        "preview_request",
    ):
        assert resolve(eligibility["properties"][field])[
            "additionalProperties"
        ] is False

    request = resolve(eligibility["properties"]["preview_request"])
    order_configuration = resolve(
        request["properties"]["order_configuration"]
    )
    limit_gtc = resolve(
        order_configuration["properties"]["limit_limit_gtc"]
    )
    assert limit_gtc["additionalProperties"] is False
    assert set(limit_gtc["properties"]) == {
        "base_size",
        "limit_price",
        "post_only",
    }

    predecessor = resolve(schema["properties"]["predecessor_binding"])
    preview_response = resolve(
        schema["properties"]["preview_response"]["anyOf"][0]
    )
    margin_ratio = resolve(
        preview_response["properties"]["margin_ratio_data"]
    )
    candidate_binding = resolve(
        preview_response["properties"]["candidate_binding"]
    )
    assert predecessor["additionalProperties"] is False
    assert preview_response["additionalProperties"] is False
    assert margin_ratio["additionalProperties"] is False
    assert candidate_binding["additionalProperties"] is False

    margin = resolve(
        eligibility["properties"]["margin_collateral_evidence"]
    )
    margin_measure = resolve(
        margin["properties"]["intraday_margin_window_measure"]
    )
    candidate = resolve(eligibility["properties"]["candidate"])
    for decimal_schema in (
        margin_measure["properties"]["maintenance_margin_usdc"],
        candidate["properties"]["product_price"],
        preview_response["properties"]["order_total"],
    ):
        assert decimal_schema["type"] == "string"
        assert decimal_schema["maxLength"] == 128
        assert decimal_schema["pattern"] == (
            r"^(?:0|[1-9]\d*)(?:\.\d+)?$"
        )


def test_r12_terminal_nested_public_models_reject_unknown_fields() -> None:
    from application.admin_api.futures_order_preview_r12 import (
        FUTURES_PREVIEW_R12_PREDECESSOR_BINDING,
    )
    from application.admin_api.models import (
        AdminFuturesPreviewR12PredecessorBinding,
        AdminFuturesPreviewR12SanitizedResponse,
    )

    attacked_predecessor = dict(FUTURES_PREVIEW_R12_PREDECESSOR_BINDING)
    attacked_predecessor["unvalidated_evidence"] = "forbidden"
    with pytest.raises(ValueError):
        AdminFuturesPreviewR12PredecessorBinding.model_validate(
            attacked_predecessor
        )

    attacked_preview = {
        "preview_id": "withheld",
        "errs": [],
        "warning": [],
        "order_total": "64.5",
        "commission_total": "0.12",
        "quote_size": "64.5",
        "base_size": "1",
        "best_bid": "6.46",
        "best_ask": "6.48",
        "order_margin_total": "10",
        "is_max": False,
        "margin_ratio_data": {
            "current_margin_ratio": "0.2",
            "projected_margin_ratio": "0.25",
        },
        "candidate_binding": {
            "status": "matched",
            "contract_count": "1",
            "authoritative_opening_reference_notional_usdc": "64.62",
            "maximum_exposure_reference_notional_usdc": "64.62",
            "buffered_close_reference_notional_usdc": "77.544",
            "branch_turnover_reference_notional_usdc": "142.164",
            "reference_rule": (
                "max_candidate_reference_preview_ask_contract_notional_"
                "order_total_plus_fee_quote_size_plus_fee"
            ),
            "opening_cap_usdc": "100",
            "exposure_cap_usdc": "150",
            "turnover_cap_usdc": "300",
            "comparison": "strictly_less_than",
        },
        "liquidation_evidence_source": "margin_ratio_data",
        "unvalidated_evidence": "forbidden",
    }
    with pytest.raises(ValueError):
        AdminFuturesPreviewR12SanitizedResponse.model_validate(attacked_preview)


def test_r12_route_serializes_only_the_validated_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_payload = {
        "artifact_type": "futures_exact_no_live_preview_slice_2r12",
        "unvalidated_nested_evidence": {"private_identifier": "raw-private-id"},
    }
    validated = AdminFuturesOrderPreviewR12Response.model_construct(
        schema_version="1",
        type="admin_futures_order_preview",
        artifact_type="futures_exact_no_live_preview_slice_2r12",
        status="blocked",
        outcome="blocked",
        blocker="predecessor_validation_blocked_after_claim",
    )
    monkeypatch.setattr(futures_routes, "require_permission", lambda *_: None)
    monkeypatch.setattr(
        AdminFuturesOrderPreviewR12Response,
        "model_validate",
        lambda _payload: validated,
    )

    response = futures_routes.get_futures_order_preview(
        actor=object(),
        store=_R12ReadStore(raw_payload),
    )

    assert json.loads(response.body) == validated.model_dump(mode="json")
    assert "unvalidated_nested_evidence" not in response.body.decode()
    assert "terminal_diagnostic_classification" not in response.body.decode()


def test_r12_route_dependency_and_absent_readback_never_touch_history(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    from fastapi import HTTPException

    import application.admin_api.futures_order_preview as preview_module
    import application.admin_api.futures_order_preview_r12 as r12_module

    r12_path = tmp_path / "absent-r12-terminal.jsonl"

    monkeypatch.setattr(
        futures_routes,
        "FUTURES_PREVIEW_R12_ARTIFACT_PATH",
        r12_path,
        raising=False,
    )
    def forbidden(*_args: Any, **_kwargs: Any) -> Any:
        pytest.fail("historical Preview selector/readback helper was invoked")

    for name in (
        "configured_futures_order_preview_artifact_path",
        "_configured_futures_order_preview_artifact_path_unlocked",
        "_configured_futures_order_preview_r11_artifact_path",
        "_configured_futures_order_preview_r8_artifact_path",
        "validate_production_futures_order_preview_r11_terminal",
        "validate_production_futures_order_preview_r8_opaque_chain",
    ):
        monkeypatch.setattr(preview_module, name, forbidden)
    for name in (
        "configured_futures_order_preview_artifact_path",
        "is_fixed_r8_forensic_artifact_path",
        "build_r8_forensic_readback",
    ):
        monkeypatch.setattr(futures_routes, name, forbidden, raising=False)
    monkeypatch.setattr(futures_routes, "require_permission", lambda *_: None)

    store = futures_routes.get_futures_order_preview_store()

    assert isinstance(store, r12_module.FuturesPreviewR12ArtifactStore)
    assert store.path == r12_path
    assert store.enforce_latest_selection is False
    with pytest.raises(HTTPException) as raised:
        futures_routes.get_futures_order_preview(
            actor=object(),
            store=store,
        )
    assert raised.value.status_code == 503
    assert raised.value.detail == (
        "Futures Preview evidence is unavailable or invalid"
    )


def test_r12_claim_only_readback_returns_fixed_sanitized_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi import HTTPException

    from application.admin_api.futures_order_preview import (
        FuturesOrderPreviewArtifactError,
    )

    class _ClaimOnlyR12Store:
        path = "/tmp/synthetic-r12-claim-only.jsonl"

        def read_completed(self) -> dict[str, Any]:
            raise FuturesOrderPreviewArtifactError(
                "private claim-only persistence detail"
            )

    monkeypatch.setattr(futures_routes, "require_permission", lambda *_: None)
    for name in (
        "is_fixed_r8_forensic_artifact_path",
        "build_r8_forensic_readback",
    ):
        monkeypatch.setattr(
            futures_routes,
            name,
            lambda *_args, **_kwargs: pytest.fail(
                "historical Preview readback helper was invoked"
            ),
            raising=False,
        )

    with pytest.raises(HTTPException) as raised:
        futures_routes.get_futures_order_preview(
            actor=object(),
            store=_ClaimOnlyR12Store(),
        )
    assert raised.value.status_code == 503
    assert raised.value.detail == (
        "Futures Preview evidence is unavailable or invalid"
    )
    assert "private" not in str(raised.value.detail).lower()
