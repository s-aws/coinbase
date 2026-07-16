from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from api.v1.app import create_app
from api.v1.routes import futures as futures_routes
from application.admin_api import futures_order_preview as preview_module
from application.admin_api.futures_order_preview import (
    FuturesOrderPreviewArtifactError,
)
from application.admin_api.futures_preview_forensic_readback import (
    AdminFuturesPreviewR8ForensicReadback,
    build_r8_forensic_readback,
)


def _readback() -> AdminFuturesPreviewR8ForensicReadback:
    return build_r8_forensic_readback(
        observed_binding=dict(preview_module.FUTURES_PREVIEW_R8_TERMINAL_BINDING)
    )


def test_r8_forensic_readback_uses_documented_sha_stat_only_and_zero_call() -> None:
    payload = _readback().model_dump(mode="json")

    assert payload["schema_version"] == "futures-preview-r8-forensic-readback-v2"
    assert payload["artifact_type"] == "futures_exact_no_live_preview_slice_2r8"
    assert payload["generation"] == "R8"
    assert payload["status"] == payload["outcome"] == "blocked"
    assert payload["blocker"] == "preflight_or_preview_blocked:Exception"
    assert payload["localized_failure_boundary"] == (
        "api_key_permissions_read_boundary"
    )
    assert payload["generation_consumed"] is True
    assert payload["artifact_file_sha256"] == (
        "b32aba4868f08ee7a44f19ceacbcf42cb7e4d70da1552f2d8b333ef59ddc8696"
    )
    assert payload["artifact_metadata"] == {
        "artifact_name": "futures_exact_no_live_preview_slice_2r8.jsonl",
        "device": "2096",
        "inode": "400341",
        "size_bytes": 14921,
        "mode": "0400",
        "mtime_ns": "1784160315297279427",
        "nlink": 1,
    }
    assert payload["read_boundary_counters"] == {
        "api_key_permissions": 1,
        "portfolio_catalog": 0,
        "product": 0,
        "best_bid_ask": 0,
        "futures_positions": 0,
        "futures_margin_collateral": 0,
    }
    assert payload["attempt_counters"] == {
        "preview_order": 0,
        "retry": 0,
        "fallback": 0,
        "create_order": 0,
        "cancel_order": 0,
        "close_position": 0,
        "reduce_position": 0,
    }
    assert payload["real_aws_service_call_count"] == 0
    assert payload["real_coinbase_request_count"] == 0
    assert payload["exchange_submission_attempt_count"] == 0
    assert payload["live_coinbase_execution"] == "not_run"
    assert payload["slice3_activated"] is False
    assert payload["documented_sha256_stat_metadata_validated"] is True
    assert payload["artifact_file_sha256_source"] == (
        "documented_preexisting_binding_not_recomputed"
    )
    assert payload["artifact_bytes_opened"] is False
    assert "opaque_hash_stat_validated" not in payload
    assert payload["raw_response_included"] is False
    assert payload["private_identifier_values_included"] is False
    assert payload["withheld_exception_text_included"] is False

    serialized = json.dumps(payload, sort_keys=True)
    assert serialized
    observed_keys: set[str] = set()

    def collect_keys(value: object) -> None:
        if isinstance(value, dict):
            observed_keys.update(str(key) for key in value)
            for nested in value.values():
                collect_keys(nested)
        elif isinstance(value, list):
            for nested in value:
                collect_keys(nested)

    collect_keys(payload)
    for forbidden_key in (
        "preview_response",
        "correlation_id",
        "idempotency_key",
        "portfolio_id",
        "preview_id",
        "exception_text",
    ):
        assert forbidden_key not in observed_keys


def test_r8_forensic_readback_rejects_any_binding_drift() -> None:
    attacked = dict(preview_module.FUTURES_PREVIEW_R8_TERMINAL_BINDING)
    attacked["preview_order_attempt_count"] = 1

    with pytest.raises(
        FuturesOrderPreviewArtifactError,
        match="R8 forensic binding changed",
    ):
        build_r8_forensic_readback(observed_binding=attacked)


def test_production_selector_hash_stat_validates_r8_without_deserializing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(
        "COINBASE_ADMIN_API_FUTURES_ORDER_PREVIEW_ARTIFACT_PATH",
        raising=False,
    )
    monkeypatch.setattr(
        preview_module,
        "_configured_futures_order_preview_r10_artifact_path",
        lambda: None,
    )
    monkeypatch.setattr(
        preview_module,
        "_configured_futures_order_preview_r9_artifact_path",
        lambda: None,
    )
    monkeypatch.setattr(
        preview_module,
        "validate_production_futures_order_preview_r8_opaque_chain",
        lambda: dict(preview_module.FUTURES_PREVIEW_R8_TERMINAL_BINDING),
    )
    monkeypatch.setattr(
        preview_module.FuturesOrderPreviewArtifactStore,
        "read_completed",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("production R8 JSON must remain opaque")
        ),
    )

    assert preview_module.configured_futures_order_preview_artifact_path() == (
        preview_module.FUTURES_PREVIEW_R8_ARTIFACT_PATH
    )


def test_order_preview_route_never_deserializes_production_r8(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class OpaqueR8Store:
        path = preview_module.FUTURES_PREVIEW_R8_ARTIFACT_PATH

        @staticmethod
        def read_completed() -> dict[str, object]:
            raise AssertionError("production R8 JSON must remain opaque")

    monkeypatch.setenv("COINBASE_ADMIN_API_BEARER_TOKEN", "test-token")
    monkeypatch.setattr(
        futures_routes,
        "build_r8_forensic_readback",
        lambda: _readback(),
        raising=False,
    )
    app = create_app()
    app.dependency_overrides[
        futures_routes.get_futures_order_preview_store
    ] = lambda: OpaqueR8Store()

    response = TestClient(app).get(
        "/api/v1/futures/order-preview",
        headers={
            "Authorization": "Bearer test-token",
            "X-Admin-Actor": "operator-1",
            "X-Admin-Roles": "viewer",
        },
    )

    assert response.status_code == 200
    assert response.json() == _readback().model_dump(mode="json")
