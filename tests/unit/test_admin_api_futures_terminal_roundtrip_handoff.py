from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import importlib
import json
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from application.admin_api import (
    futures_terminal_roundtrip_admission as admission_module,
    futures_terminal_roundtrip_handoff as handoff_module,
)
from application.admin_api.futures_order_preview import (
    FUTURES_PREVIEW_R8_ARTIFACT_TYPE,
    _withhold_r8_private_accepted_evidence,
    canonical_sha256,
)
from application.admin_api.futures_terminal_roundtrip import (
    SLICE3_ACTOR_ID,
    SLICE3_LIVE_POLICY,
    SLICE3_METHOD,
    SLICE3_PERMISSION,
    SLICE3_POLICY,
    SLICE3_PRODUCT_ID,
    SLICE3_ROLES,
    SLICE3_ROUTE,
    SLICE3_SERVICE_METHOD,
    Slice3DirectiveKind,
    Slice3ReadSlot,
)
from application.admin_api.futures_terminal_roundtrip_handoff import (
    R8Slice3HandoffError,
    build_slice3_activation_manifest,
    build_slice3_admitted_plan_from_r8,
    build_slice3_plan_from_r8,
)
from application.admin_api.futures_terminal_roundtrip_admission import (
    FileSlice3AdmissionArtifactStore,
    build_slice3_admission_chain,
)
from application.admin_api.futures_terminal_roundtrip_activation import (
    Slice3AcceptedR8Binding,
)
from application.admin_api.futures_terminal_roundtrip_coinbase import (
    Slice3CoinbaseAccountBinding,
)


NOW = datetime(2026, 7, 15, 23, 0, tzinfo=timezone.utc)
RAW_PREVIEW_ID = "private-r8-preview-handoff-601"
RAW_PORTFOLIO_ID = "private-r8-portfolio-handoff-601"
CREATE_ID = "00000000-0000-4000-8000-000000000601"
CLOSE_ID = "00000000-0000-4000-8000-000000000602"
SESSION_BINDING_TOKEN = "00000000-0000-4000-8000-000000000603"
AUTHORIZATION_TEXT = "exact synthetic Slice3 authorization"
AUTHORIZATION_SHA256 = hashlib.sha256(AUTHORIZATION_TEXT.encode("utf-8")).hexdigest()
PREVIEW_EXPIRY_CONTRACT_SHA256 = "9" * 64


def _synthetic_preview_expiry(
    *,
    response: dict[str, Any],
    accepted_at: datetime,
) -> dict[str, object]:
    del response
    return {
        "schema_version": "slice3-preview-expiry-evidence-v1",
        "source": "coinbase_documented_preview_response",
        "response_field": "preview_expires_at",
        "accepted_at": accepted_at.isoformat(),
        "expires_at": (accepted_at + timedelta(minutes=10)).isoformat(),
        "source_contract_sha256": PREVIEW_EXPIRY_CONTRACT_SHA256,
        "raw_response_included": False,
        "identifier_values_included": False,
    }


@pytest.fixture(autouse=True)
def _install_synthetic_preview_expiry_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        handoff_module,
        "COINBASE_ADVANCED_TRADE_PREVIEW_EXPIRY_CONTRACT_SHA256",
        PREVIEW_EXPIRY_CONTRACT_SHA256,
    )
    monkeypatch.setattr(
        handoff_module,
        "_load_documented_preview_expiry_evidence",
        _synthetic_preview_expiry,
    )


def _ephemeral_accepted() -> dict[str, object]:
    preview_request = {
        "product_id": SLICE3_PRODUCT_ID,
        "side": "BUY",
        "order_configuration": {
            "limit_limit_gtc": {
                "base_size": "1",
                "limit_price": "6.45",
                "post_only": True,
            }
        },
    }
    preview_response = {
        "preview_id": RAW_PREVIEW_ID,
        "commission_total": "0.12",
        "order_margin_total": "10.00",
        "candidate_binding": {
            "status": "matched",
            "authoritative_opening_reference_notional_usdc": "64.80",
        },
    }
    margin = {
        "status": "ready",
        "account_family": "coinbase_futures_us_cfm",
        "available_margin_usdc": "250.00",
        "current_margin_windows": [
            {
                "profile": "MARGIN_PROFILE_TYPE_RETAIL_REGULAR",
                "margin_window_type": "MARGIN_WINDOW_TYPE_UNSPECIFIED",
            },
            {
                "profile": ("MARGIN_PROFILE_TYPE_RETAIL_INTRADAY_MARGIN_1"),
                "margin_window_type": "MARGIN_WINDOW_TYPE_INTRADAY",
            },
        ],
    }
    candidate = {
        "product_id": SLICE3_PRODUCT_ID,
        "contract_count": "1",
        "contract_size": "10",
        "side": "BUY",
        "order_type": "LIMIT_GTC",
        "post_only": "true",
        "limit_price": "6.45",
        "reference_price": "6.48",
        "opening_reference_notional_usdc": "64.80",
        "maximum_exposure_reference_notional_usdc": "64.80",
        "buffered_close_reference_notional_usdc": "77.76",
        "branch_turnover_reference_notional_usdc": "142.56",
        "opening_cap_usdc": "100",
        "exposure_cap_usdc": "150",
        "turnover_cap_usdc": "300",
    }
    position = {
        "product_id": SLICE3_PRODUCT_ID,
        "observed_contract_count": "0",
        "sanitized": True,
        "raw_response_included": False,
    }
    seal_ready_plan = {
        "schema_version": "1",
        "slice_id": FUTURES_PREVIEW_R8_ARTIFACT_TYPE,
        "profile_binding": {
            "profile_label": "Default",
            "portfolio_type": "DEFAULT",
            "portfolio_id": RAW_PORTFOLIO_ID,
            "selection_authority": ("cdp_api_key_permissioned_portfolio"),
            "request_portfolio_override_allowed": False,
        },
        "product_id": SLICE3_PRODUCT_ID,
        "contract_count": "1",
        "candidate": deepcopy(candidate),
        "preview_request": deepcopy(preview_request),
        "preview_request_sha256": canonical_sha256(preview_request),
        "authoritative_preview": {
            "preview_id": RAW_PREVIEW_ID,
            "preview_response": deepcopy(preview_response),
            "preview_response_sha256": canonical_sha256(preview_response),
            "candidate_binding": deepcopy(preview_response["candidate_binding"]),
            "commission_total": "0.12",
            "order_margin_total": "10.00",
        },
        "caps": {
            "opening_reference_notional_usdc": "100",
            "concurrent_exposure_usdc": "150",
            "buffered_close_reference_notional_usdc": "150",
            "branch_turnover_reference_notional_usdc": "300",
            "comparison": "strictly_less_than",
        },
        "attempt_policy": {
            "preview_order": 1,
            "retry": 0,
            "fallback": 0,
            "create_order": 0,
            "cancel_order": 0,
            "close_position": 0,
            "reduce_position": 0,
        },
        "preflight_evidence_hashes": {},
        "no_live_posture": {
            "order_creation_authorized": False,
            "order_cancellation_authorized": False,
            "position_close_authorized": False,
            "position_reduce_authorized": False,
        },
    }
    evidence: dict[str, object] = {
        "schema_version": "1",
        "type": "admin_futures_order_preview",
        "artifact_type": FUTURES_PREVIEW_R8_ARTIFACT_TYPE,
        "status": "accepted",
        "outcome": "accepted",
        "claim_sha256": "1" * 64,
        "completed_at": (NOW - timedelta(seconds=5)).isoformat(),
        "product_id": SLICE3_PRODUCT_ID,
        "portfolio_id": RAW_PORTFOLIO_ID,
        "portfolio_binding": {
            "observed_portfolio_id": RAW_PORTFOLIO_ID,
            "observed_portfolio_label": "Default",
            "observed_portfolio_type": "DEFAULT",
            "can_view": True,
            "can_trade": True,
            "credential_trade_permission_present": True,
            "request_portfolio_override_allowed": False,
            "account_family": "coinbase_futures_us_cfm",
            "status": "matched",
            "ready": True,
        },
        "preview_request": preview_request,
        "preview_request_sha256": canonical_sha256(preview_request),
        "preview_response": preview_response,
        "preview_response_sha256": canonical_sha256(preview_response),
        "candidate": candidate,
        "position_evidence": position,
        "position_evidence_sha256": canonical_sha256(position),
        "margin_collateral_evidence": margin,
        "margin_collateral_evidence_sha256": canonical_sha256(margin),
        "margin_windows_policy_evidence": {
            "policy_id": "slice2_preview_margin_window_exact_pair_policy_v3",
            "schema_version": "3",
            "pair_policy_mode": "exact_profile_state_pair",
            "profile_state_mapping_documented_by_coinbase": False,
            "profile_state_policy_authority": (
                "operator_defined_slice_2_preview_only_not_coinbase_documented"
            ),
            "rows": [
                {
                    "recognized_profile": "retail_regular",
                    "observed_token": "MARGIN_WINDOW_TYPE_UNSPECIFIED",
                    "operator_policy_match": True,
                },
                {
                    "recognized_profile": "retail_intraday_margin_1",
                    "observed_token": "MARGIN_WINDOW_TYPE_INTRADAY",
                    "operator_policy_match": True,
                },
            ],
        },
        "seal_ready_plan": seal_ready_plan,
        "seal_ready_plan_sha256": canonical_sha256(seal_ready_plan),
        "attempt_counters": {
            "preview_order": 1,
            "retry": 0,
            "fallback": 0,
            "create_order": 0,
            "cancel_order": 0,
            "close_position": 0,
            "reduce_position": 0,
        },
        "read_counters": {
            "api_key_permissions": 1,
            "portfolio_catalog": 1,
            "product": 1,
            "best_bid_ask": 1,
            "futures_positions": 1,
            "futures_margin_collateral": 1,
        },
        "exchange_submission_attempt_count": 0,
        "submitted_notional_usdc": "0",
        "executed_notional_usdc": "0",
    }
    evidence["evidence_sha256"] = canonical_sha256(evidence)
    return evidence


def _pair() -> tuple[dict[str, object], dict[str, object]]:
    ephemeral = _ephemeral_accepted()
    persisted = _withhold_r8_private_accepted_evidence(ephemeral)
    return ephemeral, persisted


@pytest.fixture(scope="module")
def producer_r8_pair(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    """Capture the exact callback pair emitted by the synthetic R8 producer."""

    from application.admin_api.futures_order_preview import (
        FUTURES_PREVIEW_R7_TERMINAL_BINDING,
    )
    from tests.unit.test_admin_api_futures_order_preview import (
        NOW as PRODUCER_NOW,
        _producer,
        _r8_compatible_rest_client,
    )

    instants = iter(
        (
            PRODUCER_NOW,
            PRODUCER_NOW + timedelta(seconds=1),
            PRODUCER_NOW + timedelta(seconds=2),
            PRODUCER_NOW + timedelta(seconds=3),
        )
    )
    rest_client = _r8_compatible_rest_client()
    margin_snapshot = rest_client.get_futures_margin_collateral_snapshot()
    margin_snapshot["intraday_margin_setting"]["setting"] = (  # type: ignore[index]
        "INTRADAY_MARGIN_SETTING_INTRADAY"
    )
    producer, store, artifact_path = _producer(
        tmp_path_factory.mktemp("slice3-handoff-producer"),
        rest_client,
        artifact_type=FUTURES_PREVIEW_R8_ARTIFACT_TYPE,
        predecessor_binding=FUTURES_PREVIEW_R7_TERMINAL_BINDING,
        now=lambda: next(instants),
    )
    callback: dict[str, dict[str, Any]] = {}

    def capture(
        ephemeral: dict[str, Any],
        persisted: dict[str, Any],
    ) -> None:
        callback["ephemeral"] = deepcopy(ephemeral)
        callback["persisted"] = deepcopy(persisted)

    terminal = producer.run(accepted_callback=capture)
    ephemeral = callback["ephemeral"]
    persisted = callback["persisted"]
    assert terminal == persisted == store.read_completed()
    assert _withhold_r8_private_accepted_evidence(ephemeral) == persisted
    assert ephemeral["portfolio_binding"]["observed_at"] == (
        PRODUCER_NOW + timedelta(seconds=1)
    ).isoformat().replace("+00:00", "Z")
    assert ephemeral["candidate"]["observed_at"] == (
        PRODUCER_NOW + timedelta(seconds=2)
    ).isoformat().replace("+00:00", "Z")
    assert ephemeral["completed_at"] == (
        PRODUCER_NOW + timedelta(seconds=3)
    ).isoformat().replace("+00:00", "Z")
    return (
        ephemeral,
        persisted,
        hashlib.sha256(artifact_path.read_bytes()).hexdigest(),
    )


def _handoff_now(ephemeral: dict[str, Any]) -> datetime:
    completed = datetime.fromisoformat(str(ephemeral["completed_at"]))
    return completed.astimezone(timezone.utc) + timedelta(seconds=5)


def _account_binding(
    ephemeral: dict[str, Any],
) -> Slice3CoinbaseAccountBinding:
    return Slice3CoinbaseAccountBinding.build(
        portfolio_id=str(ephemeral["portfolio_id"]),
        session_binding_token=SESSION_BINDING_TOKEN,
        permission_evidence_sha256=str(ephemeral["permission_evidence_sha256"]),
        portfolio_catalog_sha256=str(ephemeral["portfolio_catalog_sha256"]),
    )


def _adapter_evidence_sha256(ephemeral: dict[str, Any]) -> str:
    return _account_binding(ephemeral).adapter_evidence_sha256


def _rehash_pair(
    ephemeral: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Recompute every producer hash after a self-consistent attack."""

    for field, hash_field in (
        ("permission_evidence", "permission_evidence_sha256"),
        ("portfolio_catalog_evidence", "portfolio_catalog_sha256"),
        ("product_evidence", "product_evidence_sha256"),
        ("market_evidence", "market_evidence_sha256"),
        ("position_evidence", "position_evidence_sha256"),
        ("margin_collateral_evidence", "margin_collateral_evidence_sha256"),
        ("margin_setting_evidence", "margin_setting_evidence_sha256"),
        ("margin_windows_policy_evidence", "margin_windows_policy_evidence_sha256"),
        ("candidate", "candidate_sha256"),
        ("preview_request", "preview_request_sha256"),
        ("preview_response", "preview_response_sha256"),
    ):
        ephemeral[hash_field] = canonical_sha256(ephemeral[field])
    seal = ephemeral["seal_ready_plan"]
    assert isinstance(seal, dict)
    seal["preview_request_sha256"] = canonical_sha256(seal["preview_request"])
    authoritative = seal["authoritative_preview"]
    assert isinstance(authoritative, dict)
    authoritative["margin_collateral_evidence_sha256"] = ephemeral[
        "margin_collateral_evidence_sha256"
    ]
    authoritative["preview_response_sha256"] = canonical_sha256(
        authoritative["preview_response"]
    )
    preflight = seal["preflight_evidence_hashes"]
    assert isinstance(preflight, dict)
    preflight.update(
        {
            "permissions": ephemeral["permission_evidence_sha256"],
            "portfolio_catalog": ephemeral["portfolio_catalog_sha256"],
            "product": ephemeral["product_evidence_sha256"],
            "market": ephemeral["market_evidence_sha256"],
            "positions": ephemeral["position_evidence_sha256"],
            "margin_collateral": ephemeral["margin_collateral_evidence_sha256"],
            "margin_windows_policy_evidence": ephemeral[
                "margin_windows_policy_evidence_sha256"
            ],
        }
    )
    ephemeral["seal_ready_plan_sha256"] = canonical_sha256(seal)
    ephemeral["evidence_sha256"] = canonical_sha256(
        {key: value for key, value in ephemeral.items() if key != "evidence_sha256"}
    )
    return ephemeral, _withhold_r8_private_accepted_evidence(ephemeral)


def _id_factory() -> Callable[[], UUID]:
    values = iter((UUID(CREATE_ID), UUID(CLOSE_ID)))
    return lambda: next(values)


def _module_sha256(module_name: str) -> str:
    module = importlib.import_module(module_name)
    path = Path(str(module.__file__)).resolve()
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _self_consistent_attack(
    source: dict[str, Any],
    attack: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    ephemeral = deepcopy(source)
    seal = ephemeral["seal_ready_plan"]
    assert isinstance(seal, dict)
    authoritative = seal["authoritative_preview"]
    assert isinstance(authoritative, dict)

    if attack == "top_level_no_live_posture":
        ephemeral["read_only"] = False
    elif attack == "predecessor_binding":
        replacement = {"artifact_name": "self-consistent-r7-tamper"}
        ephemeral["predecessor_binding"] = deepcopy(replacement)
        seal["predecessor_binding"] = deepcopy(replacement)
    elif attack == "portfolio_command_authority":
        ephemeral["portfolio_binding"]["command_authority_granted"] = True
    elif attack == "permission_evidence":
        ephemeral["permission_evidence"]["can_trade"] = False
    elif attack == "product_contract_size":
        ephemeral["product_evidence"]["future_product_details"]["contract_size"] = "11"
    elif attack == "market_reference":
        ephemeral["market_evidence"]["best_ask"] = "6.49"
    elif attack == "margin_killswitch":
        ephemeral["margin_collateral_evidence"]["current_margin_windows"][0][
            "is_intraday_margin_killswitch_enabled"
        ] = True
    elif attack == "v3_policy_execution":
        ephemeral["margin_windows_policy_evidence"]["execution_allowed"] = True
        seal["margin_window_policy_binding"]["execution_allowed"] = True
    elif attack == "preview_schema":
        ephemeral["preview_response_schema_binding"][
            "predicted_liquidation_price_required"
        ] = True
        seal["preview_response_schema_binding"][
            "predicted_liquidation_price_required"
        ] = True
    elif attack == "post_preview_diagnostic":
        ephemeral["post_preview_diagnostic_binding"]["identifier_values_included"] = (
            True
        )
        seal["post_preview_diagnostic_binding"]["identifier_values_included"] = True
    elif attack == "seal_attempt_policy":
        seal["attempt_policy"]["create_order"] = 1
    elif attack == "seal_no_live_posture":
        seal["no_live_posture"]["order_creation_authorized"] = True
    elif attack == "liquidation_binding":
        authoritative["liquidation_evidence"] = {
            "margin_ratio_data": {
                "current_margin_ratio": "0.90",
                "projected_margin_ratio": "0.95",
            }
        }
    elif attack == "preview_order_total":
        ephemeral["preview_response"]["order_total"] = "90.00"
        authoritative["preview_response"]["order_total"] = "90.00"
    elif attack == "maximum_exposure":
        for candidate in (ephemeral["candidate"], seal["candidate"]):
            candidate["maximum_exposure_reference_notional_usdc"] = "65.00"
        for binding in (
            ephemeral["preview_response"]["candidate_binding"],
            authoritative["preview_response"]["candidate_binding"],
            authoritative["candidate_binding"],
        ):
            binding["maximum_exposure_reference_notional_usdc"] = "65.00"
    elif attack == "close_buffer_formula":
        for candidate in (ephemeral["candidate"], seal["candidate"]):
            candidate["buffered_close_reference_notional_usdc"] = "78.00"
            candidate["branch_turnover_reference_notional_usdc"] = "142.80"
        for binding in (
            ephemeral["preview_response"]["candidate_binding"],
            authoritative["preview_response"]["candidate_binding"],
            authoritative["candidate_binding"],
        ):
            binding["buffered_close_reference_notional_usdc"] = "78.00"
            binding["branch_turnover_reference_notional_usdc"] = "142.80"
    else:  # pragma: no cover - test table is exhaustive
        raise AssertionError(f"unknown attack: {attack}")
    return _rehash_pair(ephemeral)


def test_builds_exact_private_free_live_plan_from_ephemeral_r8(
    producer_r8_pair: tuple[dict[str, Any], dict[str, Any], str],
) -> None:
    ephemeral, persisted, _artifact_sha256 = producer_r8_pair
    now = _handoff_now(ephemeral)

    plan = build_slice3_plan_from_r8(
        ephemeral_evidence=ephemeral,
        persisted_terminal=persisted,
        authorization_sha256=AUTHORIZATION_SHA256,
        adapter_evidence_sha256=_adapter_evidence_sha256(ephemeral),
        now=now,
        backend_revision="backend-main-test",
        openapi_revision="openapi-test",
        client_order_id_factory=_id_factory(),
    )

    preview_id = str(ephemeral["preview_response"]["preview_id"])
    portfolio_id = str(ephemeral["portfolio_id"])
    assert plan.policy == SLICE3_LIVE_POLICY
    assert plan.create.preview_id == preview_id
    assert plan.portfolio.portfolio_id == portfolio_id
    assert plan.create.client_order_id == CREATE_ID
    assert plan.close_client_order_id == CLOSE_ID
    assert plan.create.preview_request() == ephemeral["preview_request"]
    assert plan.preview.candidate_reference_price == "6.48"
    assert plan.preview.candidate_opening_reference_usdc == "64.80"
    assert plan.preview.commission_total == "0.12"
    assert plan.preview.order_margin_total == "10.00"
    assert plan.preview.available_margin_usdc == "250.00"
    assert plan.expires_at - plan.preview.accepted_at == timedelta(minutes=10)
    assert plan.expires_at == now + timedelta(minutes=9, seconds=55)
    assert plan.preview.expiry_source == "coinbase_documented_preview_response"
    assert plan.preview.expiry_evidence_sha256 == canonical_sha256(
        _synthetic_preview_expiry(
            response=ephemeral["preview_response"],
            accepted_at=plan.preview.accepted_at,
        )
    )
    assert plan.risk_off_expires_at - plan.preview.accepted_at == timedelta(minutes=15)
    assert plan.baseline_position_contracts == Decimal("0")
    assert plan.caps.opening == Decimal("64.80")
    assert plan.caps.exposure == Decimal("64.80")
    assert plan.caps.close == Decimal("77.76")
    assert plan.caps.turnover == Decimal("142.56")
    assert Decimal(plan.preview.available_margin_usdc) > (
        Decimal(plan.preview.order_margin_total)
        + Decimal(plan.preview.commission_total)
    )
    assert UUID(plan.create.client_order_id).version == 4
    assert UUID(plan.close_client_order_id).version == 4
    assert _withhold_r8_private_accepted_evidence(ephemeral) == persisted
    assert ephemeral["evidence_sha256"] == canonical_sha256(
        {key: value for key, value in ephemeral.items() if key != "evidence_sha256"}
    )
    assert persisted["evidence_sha256"] == canonical_sha256(
        {key: value for key, value in persisted.items() if key != "evidence_sha256"}
    )

    serialized = json.dumps(plan.sanitized_evidence(), sort_keys=True)
    rendered = repr(plan)
    for private in (
        preview_id,
        portfolio_id,
        CREATE_ID,
        CLOSE_ID,
        str(ephemeral["correlation_id"]),
        str(ephemeral["idempotency_key"]),
        SESSION_BINDING_TOKEN,
    ):
        assert private not in serialized
        assert private not in rendered


def test_handoff_requires_authoritative_coinbase_preview_expiry_evidence(
    producer_r8_pair: tuple[dict[str, Any], dict[str, Any], str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ephemeral, persisted, _artifact_sha256 = producer_r8_pair
    monkeypatch.setattr(
        handoff_module,
        "_load_documented_preview_expiry_evidence",
        lambda **_kwargs: None,
    )

    with pytest.raises(R8Slice3HandoffError, match="preview_expiry_unavailable"):
        build_slice3_plan_from_r8(
            ephemeral_evidence=ephemeral,
            persisted_terminal=persisted,
            authorization_sha256=AUTHORIZATION_SHA256,
            adapter_evidence_sha256=_adapter_evidence_sha256(ephemeral),
            now=_handoff_now(ephemeral),
            backend_revision="backend-main-test",
            openapi_revision="openapi-test",
            client_order_id_factory=_id_factory(),
        )


def test_execution_authority_hashes_bind_exact_r8_and_account_contracts(
    producer_r8_pair: tuple[dict[str, Any], dict[str, Any], str],
) -> None:
    ephemeral, persisted, _artifact_sha256 = producer_r8_pair
    plan = build_slice3_plan_from_r8(
        ephemeral_evidence=ephemeral,
        persisted_terminal=persisted,
        authorization_sha256=AUTHORIZATION_SHA256,
        adapter_evidence_sha256=_adapter_evidence_sha256(ephemeral),
        now=_handoff_now(ephemeral),
        backend_revision="backend-main-test",
        openapi_revision="openapi-test",
        client_order_id_factory=_id_factory(),
    )
    authority = plan.execution_authority
    candidate = ephemeral["candidate"]
    response = ephemeral["preview_response"]
    portfolio_id = str(ephemeral["portfolio_id"])
    account_binding = _account_binding(ephemeral)

    assert authority.actor_id == ephemeral["actor_id"] == SLICE3_ACTOR_ID
    assert authority.roles == tuple(ephemeral["roles"]) == SLICE3_ROLES
    assert authority.correlation_id == ephemeral["correlation_id"]
    assert authority.preview_idempotency_key == ephemeral["idempotency_key"]
    assert UUID(authority.correlation_id).version == 4
    assert UUID(authority.preview_idempotency_key).version == 4
    assert authority.authorization_sha256 == AUTHORIZATION_SHA256
    assert authority.approval_evidence_sha256 == canonical_sha256(
        {
            "authorization_sha256": AUTHORIZATION_SHA256,
            "actor_id": SLICE3_ACTOR_ID,
            "roles": list(SLICE3_ROLES),
        }
    )
    assert authority.admission_evidence_sha256 == canonical_sha256(
        {
            "product_id": SLICE3_PRODUCT_ID,
            "contract_count": "1",
            "side": "BUY",
            "portfolio_id_sha256": hashlib.sha256(
                portfolio_id.encode("utf-8")
            ).hexdigest(),
            "permission_evidence_sha256": ephemeral["permission_evidence_sha256"],
            "portfolio_catalog_sha256": ephemeral["portfolio_catalog_sha256"],
            "preview_request_sha256": ephemeral["preview_request_sha256"],
        }
    )
    assert authority.cap_guard_evidence_sha256 == canonical_sha256(
        {
            "opening_reference_notional_usdc": candidate[
                "opening_reference_notional_usdc"
            ],
            "maximum_exposure_reference_notional_usdc": candidate[
                "maximum_exposure_reference_notional_usdc"
            ],
            "buffered_close_reference_notional_usdc": candidate[
                "buffered_close_reference_notional_usdc"
            ],
            "branch_turnover_reference_notional_usdc": candidate[
                "branch_turnover_reference_notional_usdc"
            ],
            "opening_cap_usdc": "100",
            "exposure_cap_usdc": "150",
            "turnover_cap_usdc": "300",
            "comparison": "strictly_less_than",
        }
    )
    assert authority.reconciliation_evidence_sha256 == canonical_sha256(
        {
            "directives": [item.value for item in Slice3DirectiveKind],
            "read_slots": [item.value for item in Slice3ReadSlot],
            "read_attempt_limit_per_slot": 1,
            "polling_allowed": False,
            "pagination_allowed": False,
            "retry_allowed": False,
            "fallback_allowed": False,
            "redirect_allowed": False,
        }
    )
    assert authority.live_service_evidence_sha256 == canonical_sha256(
        {
            "route": SLICE3_ROUTE,
            "method": SLICE3_METHOD,
            "service_method": SLICE3_SERVICE_METHOD,
            "permission": SLICE3_PERMISSION,
            "live_policy_sha256": canonical_sha256(
                SLICE3_LIVE_POLICY.sanitized_evidence()
            ),
        }
    )
    assert authority.adapter_evidence_sha256 == account_binding.adapter_evidence_sha256
    assert (
        account_binding.portfolio_id_sha256
        == hashlib.sha256(portfolio_id.encode("utf-8")).hexdigest()
    )
    assert (
        account_binding.session_binding_token_sha256
        == hashlib.sha256(SESSION_BINDING_TOKEN.encode("utf-8")).hexdigest()
    )
    assert UUID(SESSION_BINDING_TOKEN).version == 4
    assert (
        account_binding.permission_evidence_sha256
        == ephemeral["permission_evidence_sha256"]
    )
    assert (
        account_binding.portfolio_catalog_sha256
        == ephemeral["portfolio_catalog_sha256"]
    )
    assert portfolio_id not in repr(account_binding)
    assert SESSION_BINDING_TOKEN not in repr(account_binding)
    assert (
        account_binding.sanitized_evidence()["same_session_preview_and_slice3"] is True
    )
    assert (
        account_binding.sanitized_evidence()["raw_identifier_values_included"] is False
    )
    assert authority.product_evidence_sha256 == ephemeral["product_evidence_sha256"]
    assert authority.market_evidence_sha256 == ephemeral["market_evidence_sha256"]
    assert (
        authority.margin_collateral_evidence_sha256
        == ephemeral["margin_collateral_evidence_sha256"]
    )
    assert authority.liquidation_evidence_sha256 == canonical_sha256(
        {
            "source": response["liquidation_evidence_source"],
            "evidence": {"margin_ratio_data": response["margin_ratio_data"]},
            "preview_response_schema_binding": ephemeral[
                "preview_response_schema_binding"
            ],
        }
    )
    assert authority.fee_funding_evidence_sha256 == canonical_sha256(
        {
            "commission_total": response["commission_total"],
            "order_margin_total": response["order_margin_total"],
            "available_margin_usdc": ephemeral["margin_collateral_evidence"][
                "available_margin_usdc"
            ],
            "funding_rule": (
                "available_margin_strictly_greater_than_order_margin_plus_commission"
            ),
        }
    )


def test_admitted_handoff_uses_the_canonical_preplan_authority_bundle(
    producer_r8_pair: tuple[dict[str, Any], dict[str, Any], str],
) -> None:
    from application.admin_api.futures_terminal_roundtrip_activation import (
        Slice3AcceptedR8Binding,
    )
    from application.admin_api.futures_terminal_roundtrip_admission import (
        SLICE3_OPERATOR_AUTHORIZATION_SHA256,
    )
    from application.admin_api.futures_terminal_roundtrip_handoff import (
        build_slice3_admitted_plan_from_r8,
    )

    ephemeral, persisted, artifact_sha256 = producer_r8_pair
    now = _handoff_now(ephemeral)
    accepted_r8_binding = Slice3AcceptedR8Binding.from_accepted_evidence(
        artifact_file_sha256=artifact_sha256,
        evidence=persisted,
    )

    plan, authority_bundle = build_slice3_admitted_plan_from_r8(
        ephemeral_evidence=ephemeral,
        persisted_terminal=persisted,
        accepted_r8_binding=accepted_r8_binding,
        account_binding=_account_binding(ephemeral),
        authorization_sha256=SLICE3_OPERATOR_AUTHORIZATION_SHA256,
        now=now,
        backend_revision="backend-main-test",
        openapi_revision="openapi-test",
        client_order_id_factory=_id_factory(),
    )

    assert plan.execution_authority is authority_bundle.authority
    assert plan.execution_authority.authorization_sha256 == (
        SLICE3_OPERATOR_AUTHORIZATION_SHA256
    )
    authority_bundle.validate_plan(plan, now=now)


def test_admitted_handoff_rejects_unbound_r8_account_or_authorization(
    producer_r8_pair: tuple[dict[str, Any], dict[str, Any], str],
) -> None:
    from application.admin_api.futures_terminal_roundtrip_activation import (
        Slice3AcceptedR8Binding,
    )
    from application.admin_api.futures_terminal_roundtrip_admission import (
        SLICE3_OPERATOR_AUTHORIZATION_SHA256,
    )
    from application.admin_api.futures_terminal_roundtrip_handoff import (
        build_slice3_admitted_plan_from_r8,
    )

    ephemeral, persisted, artifact_sha256 = producer_r8_pair
    accepted_r8_binding = Slice3AcceptedR8Binding.from_accepted_evidence(
        artifact_file_sha256=artifact_sha256,
        evidence=persisted,
    )
    kwargs = {
        "ephemeral_evidence": ephemeral,
        "persisted_terminal": persisted,
        "accepted_r8_binding": accepted_r8_binding,
        "account_binding": _account_binding(ephemeral),
        "authorization_sha256": SLICE3_OPERATOR_AUTHORIZATION_SHA256,
        "now": _handoff_now(ephemeral),
        "backend_revision": "backend-main-test",
        "openapi_revision": "openapi-test",
        "client_order_id_factory": _id_factory(),
    }

    with pytest.raises(R8Slice3HandoffError):
        build_slice3_admitted_plan_from_r8(
            **{
                **kwargs,
                "accepted_r8_binding": replace(
                    accepted_r8_binding,
                    evidence_sha256="f" * 64,
                ),
            }
        )

    wrong_account = Slice3CoinbaseAccountBinding.build(
        portfolio_id="different-private-portfolio",
        session_binding_token=SESSION_BINDING_TOKEN,
        permission_evidence_sha256=str(ephemeral["permission_evidence_sha256"]),
        portfolio_catalog_sha256=str(ephemeral["portfolio_catalog_sha256"]),
    )
    with pytest.raises(R8Slice3HandoffError):
        build_slice3_admitted_plan_from_r8(
            **{
                **kwargs,
                "account_binding": wrong_account,
                "client_order_id_factory": _id_factory(),
            }
        )

    with pytest.raises(R8Slice3HandoffError):
        build_slice3_admitted_plan_from_r8(
            **{
                **kwargs,
                "authorization_sha256": "f" * 64,
                "client_order_id_factory": _id_factory(),
            }
        )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda ephemeral, persisted: persisted.update(preview_id_sha256="f" * 64),
        lambda ephemeral, persisted: ephemeral["candidate"].update(
            reference_price="6.47"
        ),
        lambda ephemeral, persisted: ephemeral.update(product_id="OTHER-PRODUCT"),
        lambda ephemeral, persisted: ephemeral["portfolio_binding"].update(
            can_trade=False
        ),
        lambda ephemeral, persisted: ephemeral["position_evidence"].update(
            observed_contract_count="1"
        ),
        lambda ephemeral, persisted: ephemeral["margin_windows_policy_evidence"][
            "rows"
        ][0].update(observed_token="MARGIN_WINDOW_TYPE_INTRADAY"),
    ],
)
def test_rejects_any_ephemeral_persisted_or_policy_drift(
    mutate: Any,
    producer_r8_pair: tuple[dict[str, Any], dict[str, Any], str],
) -> None:
    source, terminal, _artifact_sha256 = producer_r8_pair
    ephemeral = deepcopy(source)
    persisted = deepcopy(terminal)
    mutate(ephemeral, persisted)

    with pytest.raises(R8Slice3HandoffError):
        build_slice3_plan_from_r8(
            ephemeral_evidence=ephemeral,
            persisted_terminal=persisted,
            authorization_sha256=AUTHORIZATION_SHA256,
            adapter_evidence_sha256=_adapter_evidence_sha256(source),
            now=_handoff_now(source),
            backend_revision="backend-main-test",
            openapi_revision="openapi-test",
            client_order_id_factory=_id_factory(),
        )


@pytest.mark.parametrize(
    "attack",
    [
        "top_level_no_live_posture",
        "predecessor_binding",
        "portfolio_command_authority",
        "permission_evidence",
        "product_contract_size",
        "market_reference",
        "margin_killswitch",
        "v3_policy_execution",
        "preview_schema",
        "post_preview_diagnostic",
        "seal_attempt_policy",
        "seal_no_live_posture",
        "liquidation_binding",
        "preview_order_total",
        "maximum_exposure",
        "close_buffer_formula",
    ],
)
def test_rejects_self_consistent_nested_tamper_with_all_hashes_recomputed(
    attack: str,
    producer_r8_pair: tuple[dict[str, Any], dict[str, Any], str],
) -> None:
    source, _terminal, _artifact_sha256 = producer_r8_pair
    ephemeral, persisted = _self_consistent_attack(source, attack)
    assert _withhold_r8_private_accepted_evidence(ephemeral) == persisted
    assert ephemeral["evidence_sha256"] == canonical_sha256(
        {key: value for key, value in ephemeral.items() if key != "evidence_sha256"}
    )
    assert persisted["evidence_sha256"] == canonical_sha256(
        {key: value for key, value in persisted.items() if key != "evidence_sha256"}
    )

    with pytest.raises(R8Slice3HandoffError):
        build_slice3_plan_from_r8(
            ephemeral_evidence=ephemeral,
            persisted_terminal=persisted,
            authorization_sha256=AUTHORIZATION_SHA256,
            adapter_evidence_sha256=_adapter_evidence_sha256(source),
            now=_handoff_now(source),
            backend_revision="backend-main-test",
            openapi_revision="openapi-test",
            client_order_id_factory=_id_factory(),
        )


def test_rejects_naive_now_and_naive_r8_completion_time(
    producer_r8_pair: tuple[dict[str, Any], dict[str, Any], str],
) -> None:
    source, terminal, _artifact_sha256 = producer_r8_pair
    with pytest.raises(R8Slice3HandoffError, match="now_invalid"):
        build_slice3_plan_from_r8(
            ephemeral_evidence=source,
            persisted_terminal=terminal,
            authorization_sha256=AUTHORIZATION_SHA256,
            adapter_evidence_sha256=_adapter_evidence_sha256(source),
            now=_handoff_now(source).replace(tzinfo=None),
            backend_revision="backend-main-test",
            openapi_revision="openapi-test",
            client_order_id_factory=_id_factory(),
        )

    ephemeral = deepcopy(source)
    ephemeral["completed_at"] = (
        datetime.fromisoformat(str(source["completed_at"]))
        .replace(tzinfo=None)
        .isoformat()
    )
    ephemeral, persisted = _rehash_pair(ephemeral)
    with pytest.raises(R8Slice3HandoffError, match="completed_at_invalid"):
        build_slice3_plan_from_r8(
            ephemeral_evidence=ephemeral,
            persisted_terminal=persisted,
            authorization_sha256=AUTHORIZATION_SHA256,
            adapter_evidence_sha256=_adapter_evidence_sha256(source),
            now=_handoff_now(source),
            backend_revision="backend-main-test",
            openapi_revision="openapi-test",
            client_order_id_factory=_id_factory(),
        )


def test_rejects_unbound_authorization_or_adapter_digest(
    producer_r8_pair: tuple[dict[str, Any], dict[str, Any], str],
) -> None:
    ephemeral, persisted, _artifact_sha256 = producer_r8_pair
    with pytest.raises(R8Slice3HandoffError, match="authorization_sha256_invalid"):
        build_slice3_plan_from_r8(
            ephemeral_evidence=ephemeral,
            persisted_terminal=persisted,
            authorization_sha256="not-a-sha256",
            adapter_evidence_sha256=_adapter_evidence_sha256(ephemeral),
            now=_handoff_now(ephemeral),
            backend_revision="backend-main-test",
            openapi_revision="openapi-test",
            client_order_id_factory=_id_factory(),
        )

    with pytest.raises(
        R8Slice3HandoffError,
        match="adapter_evidence_sha256_invalid",
    ):
        build_slice3_plan_from_r8(
            ephemeral_evidence=ephemeral,
            persisted_terminal=persisted,
            authorization_sha256=AUTHORIZATION_SHA256,
            adapter_evidence_sha256="not-a-sha256",
            now=_handoff_now(ephemeral),
            backend_revision="backend-main-test",
            openapi_revision="openapi-test",
            client_order_id_factory=_id_factory(),
        )


def test_rejects_stale_handoff_and_non_v4_or_colliding_ids(
    producer_r8_pair: tuple[dict[str, Any], dict[str, Any], str],
) -> None:
    source, terminal, _artifact_sha256 = producer_r8_pair
    ephemeral = deepcopy(source)
    persisted = deepcopy(terminal)
    accepted_at = datetime.fromisoformat(str(ephemeral["completed_at"]))
    with pytest.raises(R8Slice3HandoffError, match="stale"):
        build_slice3_plan_from_r8(
            ephemeral_evidence=ephemeral,
            persisted_terminal=persisted,
            authorization_sha256=AUTHORIZATION_SHA256,
            adapter_evidence_sha256=_adapter_evidence_sha256(source),
            now=accepted_at + timedelta(seconds=60),
            backend_revision="backend-main-test",
            openapi_revision="openapi-test",
            client_order_id_factory=_id_factory(),
        )

    for values in (
        (UUID(int=1), UUID(int=2)),
        (UUID(CREATE_ID), UUID(CREATE_ID)),
    ):
        ephemeral = deepcopy(source)
        persisted = deepcopy(terminal)
        iterator = iter(values)
        with pytest.raises(R8Slice3HandoffError, match="client_order_id"):
            build_slice3_plan_from_r8(
                ephemeral_evidence=ephemeral,
                persisted_terminal=persisted,
                authorization_sha256=AUTHORIZATION_SHA256,
                adapter_evidence_sha256=_adapter_evidence_sha256(source),
                now=_handoff_now(source),
                backend_revision="backend-main-test",
                openapi_revision="openapi-test",
                client_order_id_factory=lambda: next(iterator),
            )


def test_activation_manifest_binds_exact_files_schemas_policy_and_auth(
    producer_r8_pair: tuple[dict[str, Any], dict[str, Any], str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ephemeral, persisted, artifact_sha256 = producer_r8_pair
    now = _handoff_now(ephemeral)
    monkeypatch.setattr(
        admission_module,
        "SLICE3_OPERATOR_AUTHORIZATION_SHA256",
        AUTHORIZATION_SHA256,
    )
    accepted_binding = Slice3AcceptedR8Binding.from_accepted_evidence(
        artifact_file_sha256=artifact_sha256,
        evidence=persisted,
    )
    plan, authority_bundle = build_slice3_admitted_plan_from_r8(
        ephemeral_evidence=ephemeral,
        persisted_terminal=persisted,
        accepted_r8_binding=accepted_binding,
        account_binding=_account_binding(ephemeral),
        authorization_sha256=AUTHORIZATION_SHA256,
        now=now,
        backend_revision="backend-main-test",
        openapi_revision="openapi-test",
        client_order_id_factory=_id_factory(),
    )
    chain = build_slice3_admission_chain(
        plan=plan,
        authority_bundle=authority_bundle,
        now=now,
        expires_at=plan.risk_off_expires_at,
    )
    admission_seal = FileSlice3AdmissionArtifactStore(
        tmp_path / "slice3-admission.json"
    ).seal(chain, now=now)
    manifest = build_slice3_activation_manifest(
        plan=plan,
        persisted_terminal=persisted,
        r8_artifact_file_sha256=artifact_sha256,
        admission_seal=admission_seal,
        authorization_text=AUTHORIZATION_TEXT,
        now=now,
    )

    assert manifest.slice3_plan_sha256 == plan.plan_sha256
    assert manifest.r8_binding.artifact_file_sha256 == artifact_sha256
    assert (
        manifest.r8_binding.preview_id_sha256
        == hashlib.sha256(
            str(ephemeral["preview_response"]["preview_id"]).encode("utf-8")
        ).hexdigest()
    )
    assert manifest.expires_at == plan.risk_off_expires_at
    assert manifest.slice3_live_policy_sha256 == canonical_sha256(
        SLICE3_LIVE_POLICY.sanitized_evidence()
    )
    core_hash = _module_sha256("application.admin_api.futures_terminal_roundtrip")
    assert manifest.core_module_sha256 == core_hash
    assert manifest.port_module_sha256 == _module_sha256(
        "application.admin_api.futures_terminal_roundtrip_coinbase"
    )
    assert manifest.orchestrator_module_sha256 == _module_sha256(
        "application.admin_api.futures_terminal_roundtrip_orchestrator"
    )
    assert manifest.admission_module_sha256 == _module_sha256(
        "application.admin_api.futures_terminal_roundtrip_admission"
    )
    assert manifest.admission_chain_sha256 == admission_seal.chain_sha256
    assert manifest.admission_record_sha256 == admission_seal.record_sha256
    assert manifest.admission_artifact_file_sha256 == (
        admission_seal.artifact_file_sha256
    )
    assert manifest.action_journal_schema_sha256 == core_hash
    assert manifest.read_journal_schema_sha256 == _module_sha256(
        "application.admin_api.futures_terminal_roundtrip_reads"
    )
    assert manifest.terminal_evidence_schema_sha256 == _module_sha256(
        "application.admin_api.futures_terminal_roundtrip_terminal"
    )

    with pytest.raises(
        R8Slice3HandoffError,
        match="authorization_binding_mismatch",
    ):
        build_slice3_activation_manifest(
            plan=plan,
            persisted_terminal=persisted,
            r8_artifact_file_sha256=artifact_sha256,
            admission_seal=admission_seal,
            authorization_text="different synthetic authorization",
            now=now,
        )
    with pytest.raises(
        R8Slice3HandoffError,
        match="activation_policy_invalid",
    ):
        build_slice3_activation_manifest(
            plan=replace(plan, policy=SLICE3_POLICY),
            persisted_terminal=persisted,
            r8_artifact_file_sha256=artifact_sha256,
            admission_seal=admission_seal,
            authorization_text=AUTHORIZATION_TEXT,
            now=now,
        )

    with pytest.raises(R8Slice3HandoffError, match="admission_binding"):
        build_slice3_activation_manifest(
            plan=plan,
            persisted_terminal=persisted,
            r8_artifact_file_sha256=artifact_sha256,
            admission_seal=replace(
                admission_seal,
                chain_sha256="f" * 64,
            ),
            authorization_text=AUTHORIZATION_TEXT,
            now=now,
        )

    early_expiry_chain = replace(
        admission_seal.chain,
        expires_at=plan.expires_at,
    )
    with pytest.raises(R8Slice3HandoffError, match="admission_binding"):
        build_slice3_activation_manifest(
            plan=plan,
            persisted_terminal=persisted,
            r8_artifact_file_sha256=artifact_sha256,
            admission_seal=replace(
                admission_seal,
                chain=early_expiry_chain,
                chain_sha256=early_expiry_chain.chain_sha256,
            ),
            authorization_text=AUTHORIZATION_TEXT,
            now=now,
        )
