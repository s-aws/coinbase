from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import stat

import pytest

from application.admin_api import (
    futures_terminal_roundtrip_admission as admission_module,
)
from application.admin_api.futures_terminal_roundtrip import (
    SLICE3_ACTOR_ID,
    SLICE3_LIVE_POLICY,
    SLICE3_METHOD,
    SLICE3_PERMISSION,
    SLICE3_PRODUCT_ID,
    SLICE3_ROLES,
    SLICE3_ROUTE,
    SLICE3_SERVICE_METHOD,
    Slice3AcceptedPreview,
    Slice3CapEvidence,
    Slice3CreateRequest,
    Slice3ExecutionAuthority,
    Slice3MarginWindowEvidence,
    Slice3Plan,
    Slice3PortfolioBinding,
)
from application.admin_api.futures_terminal_roundtrip_admission import (
    SLICE3_ADMISSION_ARTIFACT_PATH,
    SLICE3_ADMISSION_GENESIS_SHA256,
    SLICE3_ADMISSION_MAX_TTL,
    SLICE3_ADMISSION_RECORD_ORDER,
    SLICE3_FIXED_CREDENTIAL_EVIDENCE_SHA256,
    SLICE3_OPERATOR_AUTHORIZATION_SHA256,
    FileSlice3AdmissionArtifactStore,
    Slice3AdmissionAuthorityBundle,
    Slice3AdmissionArtifactError,
    Slice3AdmissionChain,
    Slice3AdmissionEvidenceKind,
    Slice3AdmissionEvidenceSet,
    Slice3AdmissionSourceEvidence,
    Slice3AdmissionValidationError,
    build_slice3_admission_chain,
    build_slice3_execution_authority,
    production_slice3_admission_store,
)
from application.admin_api.futures_terminal_roundtrip_activation import (
    Slice3AcceptedR8Binding,
)
from application.admin_api.futures_terminal_roundtrip_coinbase import (
    Slice3CoinbaseAccountBinding,
)
from core.enums import OrderSide, TimeInForce


NOW = datetime(2026, 7, 15, 15, 0, tzinfo=timezone.utc)
CREATE_CLIENT_ORDER_ID = "00000000-0000-4000-8000-000000000701"
CLOSE_CLIENT_ORDER_ID = "00000000-0000-4000-8000-000000000702"
CORRELATION_ID = "00000000-0000-4000-8000-000000000711"
IDEMPOTENCY_KEY = "00000000-0000-4000-8000-000000000712"
PREVIEW_ID = "preview-private-synthetic-admission"
PORTFOLIO_ID = "portfolio-private-synthetic-admission"
SESSION_BINDING_TOKEN = "00000000-0000-4000-8000-000000000713"


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _source_id(kind: Slice3AdmissionEvidenceKind) -> str:
    return hashlib.sha256(f"{kind.value}-private-id".encode()).hexdigest()


def _portfolio() -> Slice3PortfolioBinding:
    return Slice3PortfolioBinding(
        portfolio_id=PORTFOLIO_ID,
        portfolio_name="Default",
        portfolio_type="DEFAULT",
        can_view=True,
        can_trade=True,
        product_family="US_CFM",
        intx_excluded=True,
        request_override_allowed=False,
        read_authorized=True,
        exact_match_count=1,
        selection_authority="cdp_api_key_permissioned_portfolio",
        observed_at=NOW,
        permission_evidence_sha256="9" * 64,
        portfolio_catalog_sha256="a" * 64,
    )


def _authority() -> Slice3ExecutionAuthority:
    return Slice3ExecutionAuthority(
        actor_id=SLICE3_ACTOR_ID,
        roles=SLICE3_ROLES,
        correlation_id=CORRELATION_ID,
        preview_idempotency_key=IDEMPOTENCY_KEY,
        authorization_sha256=SLICE3_OPERATOR_AUTHORIZATION_SHA256,
        route=SLICE3_ROUTE,
        method=SLICE3_METHOD,
        service_method=SLICE3_SERVICE_METHOD,
        permission=SLICE3_PERMISSION,
        approval_evidence_sha256="1" * 64,
        admission_evidence_sha256="2" * 64,
        cap_guard_evidence_sha256="3" * 64,
        reconciliation_evidence_sha256="4" * 64,
        live_service_evidence_sha256="5" * 64,
        adapter_evidence_sha256="6" * 64,
        product_evidence_sha256="7" * 64,
        market_evidence_sha256="8" * 64,
        margin_collateral_evidence_sha256="b" * 64,
        liquidation_evidence_sha256="c" * 64,
        fee_funding_evidence_sha256="d" * 64,
        observed_at=NOW,
    )


def _plan() -> Slice3Plan:
    create = Slice3CreateRequest(
        client_order_id=CREATE_CLIENT_ORDER_ID,
        preview_id=PREVIEW_ID,
        product_id=SLICE3_PRODUCT_ID,
        side=OrderSide.BUY,
        base_size="1",
        limit_price="6.40",
        post_only=True,
        time_in_force=TimeInForce.GTC,
    )
    preview = Slice3AcceptedPreview.from_request(
        accepted=True,
        preview_id=PREVIEW_ID,
        preview_request=create.preview_request(),
        accepted_at=NOW - timedelta(seconds=5),
        expires_at=NOW + timedelta(minutes=10),
        evidence_sha256="e" * 64,
        expiry_source="coinbase_documented_preview_response",
        expiry_evidence_sha256="d" * 64,
        candidate_contract_size="10",
        candidate_limit_price="6.40",
        candidate_reference_price="6.40",
        commission_total="0.12",
        order_margin_total="10",
        available_margin_usdc="250",
    )
    return Slice3Plan.build(
        policy=SLICE3_LIVE_POLICY,
        execution_authority=_authority(),
        margin_windows=Slice3MarginWindowEvidence(
            retail_regular="MARGIN_WINDOW_TYPE_UNSPECIFIED",
            retail_intraday_margin_1="MARGIN_WINDOW_TYPE_INTRADAY",
        ),
        portfolio=_portfolio(),
        preview=preview,
        create=create,
        caps=Slice3CapEvidence(
            opening_reference_usdc="64.00",
            maximum_concurrent_exposure_usdc="64.00",
            conservative_close_usdc="76.8000",
            branch_turnover_usdc="140.8000",
        ),
        close_client_order_id=CLOSE_CLIENT_ORDER_ID,
        baseline_position_contracts=Decimal("0"),
        baseline_position_sha256="f" * 64,
        backend_revision="backend-synthetic-revision",
        openapi_revision="openapi-synthetic-revision",
        now=NOW,
    )


def _source(
    kind: Slice3AdmissionEvidenceKind,
    evidence_sha256: str,
    *,
    observed_at: datetime = NOW,
    state: str | None = None,
    allowed: bool = True,
    approved: bool = True,
    evidence_id_sha256: str | None = None,
) -> Slice3AdmissionSourceEvidence:
    expected_state = {
        Slice3AdmissionEvidenceKind.APPROVAL: "approved",
        Slice3AdmissionEvidenceKind.ADMISSION_AUDIT: "allowed",
        Slice3AdmissionEvidenceKind.CAP_GUARD: "allowed",
        Slice3AdmissionEvidenceKind.RECONCILIATION: "approved",
        Slice3AdmissionEvidenceKind.LIVE_SERVICE: "enabled",
        Slice3AdmissionEvidenceKind.ADAPTER: "approved",
        Slice3AdmissionEvidenceKind.CREDENTIAL: "bound",
        Slice3AdmissionEvidenceKind.PORTFOLIO: "permission_selected",
        Slice3AdmissionEvidenceKind.PERMISSION: "allowed",
        Slice3AdmissionEvidenceKind.CATALOG: "matched",
    }[kind]
    return Slice3AdmissionSourceEvidence(
        kind=kind,
        evidence_id_sha256=evidence_id_sha256 or _source_id(kind),
        evidence_sha256=evidence_sha256,
        observed_at=observed_at,
        state=state or expected_state,
        allowed=allowed,
        approved=approved,
    )


def _evidence_set(plan: Slice3Plan) -> Slice3AdmissionEvidenceSet:
    authority = plan.execution_authority
    return Slice3AdmissionEvidenceSet(
        approval=_source(
            Slice3AdmissionEvidenceKind.APPROVAL,
            authority.approval_evidence_sha256,
        ),
        admission_audit=_source(
            Slice3AdmissionEvidenceKind.ADMISSION_AUDIT,
            authority.admission_evidence_sha256,
        ),
        cap_guard=_source(
            Slice3AdmissionEvidenceKind.CAP_GUARD,
            authority.cap_guard_evidence_sha256,
        ),
        reconciliation=_source(
            Slice3AdmissionEvidenceKind.RECONCILIATION,
            authority.reconciliation_evidence_sha256,
        ),
        live_service=_source(
            Slice3AdmissionEvidenceKind.LIVE_SERVICE,
            authority.live_service_evidence_sha256,
        ),
        adapter=_source(
            Slice3AdmissionEvidenceKind.ADAPTER,
            authority.adapter_evidence_sha256,
        ),
        credential=_source(
            Slice3AdmissionEvidenceKind.CREDENTIAL,
            SLICE3_FIXED_CREDENTIAL_EVIDENCE_SHA256,
        ),
        portfolio=_source(
            Slice3AdmissionEvidenceKind.PORTFOLIO,
            _canonical_sha256(plan.portfolio.sanitized_evidence()),
        ),
        permission=_source(
            Slice3AdmissionEvidenceKind.PERMISSION,
            plan.portfolio.permission_evidence_sha256,
        ),
        catalog=_source(
            Slice3AdmissionEvidenceKind.CATALOG,
            plan.portfolio.portfolio_catalog_sha256,
        ),
    )


def _build_authority_bundle(
    base_plan: Slice3Plan,
    *,
    authorization_sha256: str = SLICE3_OPERATOR_AUTHORIZATION_SHA256,
) -> Slice3AdmissionAuthorityBundle:
    account_binding = Slice3CoinbaseAccountBinding.build(
        portfolio_id=PORTFOLIO_ID,
        session_binding_token=SESSION_BINDING_TOKEN,
        permission_evidence_sha256=(base_plan.portfolio.permission_evidence_sha256),
        portfolio_catalog_sha256=base_plan.portfolio.portfolio_catalog_sha256,
    )
    r8_binding = Slice3AcceptedR8Binding(
        artifact_file_sha256="0" * 64,
        evidence_sha256="1" * 64,
        claim_sha256="2" * 64,
        seal_ready_plan_sha256="3" * 64,
        preview_id_sha256=base_plan.preview.preview_id_sha256,
        portfolio_id_sha256=base_plan.portfolio.portfolio_id_sha256,
    )
    return build_slice3_execution_authority(
        authorization_sha256=authorization_sha256,
        accepted_r8_binding=r8_binding,
        account_binding=account_binding,
        portfolio=base_plan.portfolio,
        create=base_plan.create,
        preview=base_plan.preview,
        caps=base_plan.caps,
        correlation_id=CORRELATION_ID,
        preview_idempotency_key=IDEMPOTENCY_KEY,
        close_client_order_id=CLOSE_CLIENT_ORDER_ID,
        product_evidence_sha256="7" * 64,
        market_evidence_sha256="8" * 64,
        margin_collateral_evidence_sha256="b" * 64,
        liquidation_evidence_sha256="c" * 64,
        fee_funding_evidence_sha256="d" * 64,
        now=NOW,
    )


def _derived_plan_and_bundle() -> tuple[
    Slice3Plan,
    Slice3AdmissionAuthorityBundle,
]:
    base_plan = _plan()
    bundle = _build_authority_bundle(base_plan)
    plan = replace(base_plan, execution_authority=bundle.authority)
    plan.validate_at(NOW)
    return plan, bundle


def _chain() -> Slice3AdmissionChain:
    plan, bundle = _derived_plan_and_bundle()
    return build_slice3_admission_chain(
        plan=plan,
        authority_bundle=bundle,
        now=NOW,
        expires_at=plan.risk_off_expires_at,
    )


def test_authority_is_derived_before_plan_from_pinned_and_validated_evidence() -> None:
    arbitrary_plan = _plan()
    account_binding = Slice3CoinbaseAccountBinding.build(
        portfolio_id=PORTFOLIO_ID,
        session_binding_token=SESSION_BINDING_TOKEN,
        permission_evidence_sha256=arbitrary_plan.portfolio.permission_evidence_sha256,
        portfolio_catalog_sha256=arbitrary_plan.portfolio.portfolio_catalog_sha256,
    )
    bundle = _build_authority_bundle(arbitrary_plan)

    assert isinstance(bundle, Slice3AdmissionAuthorityBundle)
    assert bundle.authority.authorization_sha256 == (
        SLICE3_OPERATOR_AUTHORIZATION_SHA256
    )
    assert bundle.authority.approval_evidence_sha256 != "1" * 64
    assert bundle.authority.admission_evidence_sha256 != "2" * 64
    assert bundle.authority.cap_guard_evidence_sha256 != "3" * 64
    assert bundle.authority.adapter_evidence_sha256 == (
        account_binding.adapter_evidence_sha256
    )
    assert bundle.evidence.adapter.evidence_sha256 == (
        account_binding.adapter_evidence_sha256
    )
    assert bundle.account_binding_sha256 == _canonical_sha256(
        account_binding.sanitized_evidence()
    )
    controls = bundle.control_records()
    assert _canonical_sha256(controls["approval"]) == (
        bundle.authority.approval_evidence_sha256
    )
    assert _canonical_sha256(controls["admission_audit"]) == (
        bundle.authority.admission_evidence_sha256
    )
    assert _canonical_sha256(controls["cap_guard"]) == (
        bundle.authority.cap_guard_evidence_sha256
    )
    assert _canonical_sha256(controls["reconciliation"]) == (
        bundle.authority.reconciliation_evidence_sha256
    )
    assert _canonical_sha256(controls["live_service"]) == (
        bundle.authority.live_service_evidence_sha256
    )
    assert controls["adapter"]["backed_by_slice3_coinbase_account_binding"] is True


def test_authority_builder_rejects_tampered_account_adapter_binding() -> None:
    base_plan = _plan()
    account_binding = Slice3CoinbaseAccountBinding.build(
        portfolio_id=PORTFOLIO_ID,
        session_binding_token=SESSION_BINDING_TOKEN,
        permission_evidence_sha256=base_plan.portfolio.permission_evidence_sha256,
        portfolio_catalog_sha256=base_plan.portfolio.portfolio_catalog_sha256,
    )
    attacked = replace(account_binding, adapter_evidence_sha256="0" * 64)
    r8_binding = Slice3AcceptedR8Binding(
        artifact_file_sha256="0" * 64,
        evidence_sha256="1" * 64,
        claim_sha256="2" * 64,
        seal_ready_plan_sha256="3" * 64,
        preview_id_sha256=base_plan.preview.preview_id_sha256,
        portfolio_id_sha256=base_plan.portfolio.portfolio_id_sha256,
    )
    with pytest.raises(Slice3AdmissionValidationError, match="authority_input"):
        build_slice3_execution_authority(
            authorization_sha256=SLICE3_OPERATOR_AUTHORIZATION_SHA256,
            accepted_r8_binding=r8_binding,
            account_binding=attacked,
            portfolio=base_plan.portfolio,
            create=base_plan.create,
            preview=base_plan.preview,
            caps=base_plan.caps,
            correlation_id=CORRELATION_ID,
            preview_idempotency_key=IDEMPOTENCY_KEY,
            close_client_order_id=CLOSE_CLIENT_ORDER_ID,
            product_evidence_sha256="7" * 64,
            market_evidence_sha256="8" * 64,
            margin_collateral_evidence_sha256="b" * 64,
            liquidation_evidence_sha256="c" * 64,
            fee_funding_evidence_sha256="d" * 64,
            now=NOW,
        )


def test_chain_rejects_plan_with_preexisting_arbitrary_authority() -> None:
    arbitrary_plan = _plan()
    bundle = _build_authority_bundle(arbitrary_plan)
    with pytest.raises(Slice3AdmissionValidationError, match="authority_mismatch"):
        build_slice3_admission_chain(
            plan=arbitrary_plan,
            authority_bundle=bundle,
            now=NOW,
            expires_at=arbitrary_plan.risk_off_expires_at,
        )


def test_bundle_binds_the_close_client_identity_before_plan_build() -> None:
    plan, bundle = _derived_plan_and_bundle()
    attacked_plan = replace(
        plan,
        close_client_order_id="00000000-0000-4000-8000-000000000799",
    )
    with pytest.raises(Slice3AdmissionValidationError, match="close_client_order_id"):
        bundle.validate_plan(attacked_plan, now=NOW)


def test_builds_exact_sanitized_admission_chain() -> None:
    chain = _chain()
    evidence = chain.sanitized_evidence()

    assert evidence["readiness"] == "allowed"
    assert evidence["approved"] is True
    assert evidence["allowed"] is True
    assert evidence["authorization_sha256"] == (SLICE3_OPERATOR_AUTHORIZATION_SHA256)
    expected_plan, _bundle = _derived_plan_and_bundle()
    assert evidence["plan_sha256"] == expected_plan.plan_sha256
    assert evidence["record_order"] == [
        kind.value for kind in SLICE3_ADMISSION_RECORD_ORDER
    ]
    assert evidence["record_count"] == len(SLICE3_ADMISSION_RECORD_ORDER)
    assert evidence["head_record_sha256"] == evidence["records"][-1]["record_sha256"]
    assert evidence["route_registered"] is False
    assert evidence["coinbase_calls_permitted"] is False
    assert evidence["exchange_mutations_permitted"] is False
    assert evidence["raw_private_identifier_values_included"] is False

    previous = SLICE3_ADMISSION_GENESIS_SHA256
    for index, record in enumerate(evidence["records"], start=1):
        assert record["index"] == index
        assert record["previous_record_sha256"] == previous
        unhashed = {k: v for k, v in record.items() if k != "record_sha256"}
        assert record["record_sha256"] == _canonical_sha256(unhashed)
        previous = record["record_sha256"]

    request = evidence["records"][1]["evidence"]
    assert request["actor_id"] == SLICE3_ACTOR_ID
    assert request["roles"] == ["trader"]
    assert request["route"] == SLICE3_ROUTE
    assert request["method"] == SLICE3_METHOD
    assert request["service_method"] == SLICE3_SERVICE_METHOD
    assert request["permission"] == SLICE3_PERMISSION
    assert request["product_id"] == SLICE3_PRODUCT_ID
    assert request["side"] == "BUY"
    assert request["contract_count"] == "1"
    assert request["time_in_force"] == "GTC"
    assert request["post_only"] is True
    assert request["margin_window_pair"] == {
        "retail_regular": "MARGIN_WINDOW_TYPE_UNSPECIFIED",
        "retail_intraday_margin_1": "MARGIN_WINDOW_TYPE_INTRADAY",
        "intraday_margin_setting": "INTRADAY_MARGIN_SETTING_STANDARD",
        "intraday_margin_killswitch_enabled": False,
        "intraday_margin_enrollment_killswitch_enabled": False,
    }
    assert request["caps"] == {
        "opening_reference_usdc": "64.00",
        "maximum_concurrent_exposure_usdc": "64.00",
        "conservative_close_usdc": "76.8000",
        "branch_turnover_usdc": "140.8000",
        "opening_cap": "<100",
        "exposure_and_buffered_close_cap": "<150",
        "branch_turnover_cap": "<300",
    }
    assert request["attempt_limits"] == {
        "preview": 0,
        "create": 1,
        "cancel": 1,
        "close": 1,
        "reduce": 0,
        "retry": 0,
        "fallback": 0,
        "redirect": 0,
    }

    serialized = json.dumps(evidence, sort_keys=True)
    for private_value in (
        CREATE_CLIENT_ORDER_ID,
        CLOSE_CLIENT_ORDER_ID,
        CORRELATION_ID,
        IDEMPOTENCY_KEY,
        PREVIEW_ID,
        PORTFOLIO_ID,
        SESSION_BINDING_TOKEN,
    ):
        assert private_value not in serialized
    assert "client_order_id_sha256" in serialized
    assert "close_client_order_id_sha256" in serialized
    assert "preview_id_sha256" in serialized
    assert "portfolio_id_sha256" in serialized


@pytest.mark.parametrize(
    ("field", "bad_value", "reason"),
    [
        ("authorization_sha256", "0" * 64, "authorization"),
        ("authorization_sha256", "not-a-hash", "authorization"),
    ],
)
def test_rejects_any_authorization_other_than_exact_attachment_hash(
    field: str,
    bad_value: str,
    reason: str,
) -> None:
    plan = _plan()
    with pytest.raises(Slice3AdmissionValidationError, match=reason):
        _build_authority_bundle(
            plan,
            authorization_sha256=bad_value,
        )


@pytest.mark.parametrize(
    "kind",
    [
        Slice3AdmissionEvidenceKind.APPROVAL,
        Slice3AdmissionEvidenceKind.ADMISSION_AUDIT,
        Slice3AdmissionEvidenceKind.CAP_GUARD,
        Slice3AdmissionEvidenceKind.RECONCILIATION,
        Slice3AdmissionEvidenceKind.LIVE_SERVICE,
        Slice3AdmissionEvidenceKind.ADAPTER,
        Slice3AdmissionEvidenceKind.CREDENTIAL,
        Slice3AdmissionEvidenceKind.PORTFOLIO,
        Slice3AdmissionEvidenceKind.PERMISSION,
        Slice3AdmissionEvidenceKind.CATALOG,
    ],
)
@pytest.mark.parametrize(
    ("attack", "value"),
    [
        ("state", "blocked"),
        ("allowed", False),
        ("approved", False),
        ("evidence_sha256", "0" * 64),
    ],
)
def test_every_source_must_be_fresh_exact_allowed_and_approved(
    kind: Slice3AdmissionEvidenceKind,
    attack: str,
    value: object,
) -> None:
    plan, bundle = _derived_plan_and_bundle()
    evidence = bundle.evidence
    field_name = kind.value
    source = getattr(evidence, field_name)
    attacked = replace(source, **{attack: value})
    evidence = replace(evidence, **{field_name: attacked})
    bundle = replace(bundle, evidence=evidence)

    with pytest.raises(Slice3AdmissionValidationError):
        build_slice3_admission_chain(
            plan=plan,
            authority_bundle=bundle,
            now=NOW,
            expires_at=plan.risk_off_expires_at,
        )


@pytest.mark.parametrize(
    "observed_at",
    [
        NOW - timedelta(seconds=31),
        NOW + timedelta(microseconds=1),
        datetime(2026, 7, 15, 15, 0),
    ],
)
def test_rejects_stale_future_or_naive_source_evidence(
    observed_at: datetime,
) -> None:
    plan, bundle = _derived_plan_and_bundle()
    evidence = bundle.evidence
    evidence = replace(
        evidence,
        approval=replace(evidence.approval, observed_at=observed_at),
    )
    bundle = replace(bundle, evidence=evidence)
    with pytest.raises(Slice3AdmissionValidationError):
        build_slice3_admission_chain(
            plan=plan,
            authority_bundle=bundle,
            now=NOW,
            expires_at=plan.risk_off_expires_at,
        )


@pytest.mark.parametrize(
    "expires_at",
    [
        NOW,
        NOW + SLICE3_ADMISSION_MAX_TTL + timedelta(microseconds=1),
        datetime(2026, 7, 15, 15, 1),
    ],
)
def test_rejects_invalid_or_overlong_chain_expiry(
    expires_at: datetime,
) -> None:
    plan, bundle = _derived_plan_and_bundle()
    with pytest.raises(Slice3AdmissionValidationError):
        build_slice3_admission_chain(
            plan=plan,
            authority_bundle=bundle,
            now=NOW,
            expires_at=expires_at,
        )


def test_rejects_replayed_evidence_id_across_control_records() -> None:
    plan, bundle = _derived_plan_and_bundle()
    evidence = bundle.evidence
    evidence = replace(
        evidence,
        catalog=replace(
            evidence.catalog,
            evidence_id_sha256=evidence.permission.evidence_id_sha256,
        ),
    )
    bundle = replace(bundle, evidence=evidence)
    with pytest.raises(Slice3AdmissionValidationError, match="duplicate"):
        build_slice3_admission_chain(
            plan=plan,
            authority_bundle=bundle,
            now=NOW,
            expires_at=plan.risk_off_expires_at,
        )


def test_source_factory_hashes_private_evidence_id_without_retaining_it() -> None:
    raw_id = "approval-private-id-value"
    source = Slice3AdmissionSourceEvidence.from_private_evidence_id(
        kind=Slice3AdmissionEvidenceKind.APPROVAL,
        evidence_id=raw_id,
        evidence_sha256="1" * 64,
        observed_at=NOW,
        state="approved",
        allowed=True,
        approved=True,
    )
    assert source.evidence_id_sha256 == hashlib.sha256(raw_id.encode()).hexdigest()
    assert raw_id not in repr(source)
    assert raw_id not in json.dumps(source.sanitized_evidence())


def test_chain_roundtrips_only_from_exact_sanitized_evidence() -> None:
    chain = _chain()
    restored = type(chain).from_sanitized_evidence(
        chain.sanitized_evidence(),
        now=NOW,
    )
    assert restored == chain
    assert restored.chain_sha256 == chain.chain_sha256

    attacked = chain.sanitized_evidence()
    attacked["raw_private_identifier_values_included"] = True
    with pytest.raises(Slice3AdmissionValidationError):
        type(chain).from_sanitized_evidence(attacked, now=NOW)


def test_one_chain_and_store_remain_hash_identical_for_bounded_recovery(
    tmp_path: Path,
) -> None:
    plan, bundle = _derived_plan_and_bundle()
    chain = build_slice3_admission_chain(
        plan=plan,
        authority_bundle=bundle,
        now=NOW,
        expires_at=plan.risk_off_expires_at,
    )
    recovery_at = plan.expires_at + timedelta(microseconds=1)
    assert recovery_at < plan.risk_off_expires_at
    path = tmp_path / "slice3-admission.json"
    store = FileSlice3AdmissionArtifactStore(path)
    original = store.seal(chain, now=NOW)

    recovered = store.read(
        now=recovery_at,
        expected_chain_sha256=original.chain_sha256,
    )

    assert recovered.chain_sha256 == original.chain_sha256
    assert recovered.record_sha256 == original.record_sha256
    assert recovered.artifact_file_sha256 == original.artifact_file_sha256
    assert recovered.chain == chain


def test_chain_and_store_reject_at_exact_risk_off_expiry(tmp_path: Path) -> None:
    plan, bundle = _derived_plan_and_bundle()
    chain = build_slice3_admission_chain(
        plan=plan,
        authority_bundle=bundle,
        now=NOW,
        expires_at=plan.risk_off_expires_at,
    )
    path = tmp_path / "slice3-admission.json"
    store = FileSlice3AdmissionArtifactStore(path)
    seal = store.seal(chain, now=NOW)

    with pytest.raises(Slice3AdmissionValidationError, match="expired"):
        chain.validate_at(plan.risk_off_expires_at)
    with pytest.raises(Slice3AdmissionArtifactError, match="expired"):
        store.read(
            now=plan.risk_off_expires_at,
            expected_chain_sha256=seal.chain_sha256,
        )


@pytest.mark.parametrize(
    "expires_at_offset",
    [timedelta(0), -timedelta(microseconds=1)],
)
def test_builder_requires_the_single_plan_risk_off_expiry(
    expires_at_offset: timedelta,
) -> None:
    plan, bundle = _derived_plan_and_bundle()

    with pytest.raises(Slice3AdmissionValidationError, match="expiry"):
        build_slice3_admission_chain(
            plan=plan,
            authority_bundle=bundle,
            now=NOW,
            expires_at=plan.expires_at + expires_at_offset,
        )


def test_owner_only_exclusive_artifact_seal_and_read(tmp_path: Path) -> None:
    chain = _chain()
    path = tmp_path / "slice3-admission.json"
    store = FileSlice3AdmissionArtifactStore(path)

    sealed = store.seal(chain, now=NOW)
    assert sealed.chain == chain
    assert sealed.chain_sha256 == chain.chain_sha256
    assert sealed.artifact_file_sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    metadata = path.stat()
    assert stat.S_IMODE(metadata.st_mode) == 0o400
    assert metadata.st_uid == os.geteuid()
    assert metadata.st_nlink == 1

    readback = store.read(
        now=NOW,
        expected_chain_sha256=chain.chain_sha256,
    )
    assert readback == sealed
    raw = path.read_text(encoding="utf-8")
    for private_value in (
        CREATE_CLIENT_ORDER_ID,
        CLOSE_CLIENT_ORDER_ID,
        CORRELATION_ID,
        IDEMPOTENCY_KEY,
        PREVIEW_ID,
        PORTFOLIO_ID,
        SESSION_BINDING_TOKEN,
    ):
        assert private_value not in raw

    with pytest.raises(Slice3AdmissionArtifactError, match="already_exists"):
        store.seal(chain, now=NOW)


@pytest.mark.parametrize("attack", ["mode", "hardlink", "content"])
def test_read_fails_closed_for_metadata_or_content_tamper(
    tmp_path: Path,
    attack: str,
) -> None:
    chain = _chain()
    path = tmp_path / "slice3-admission.json"
    store = FileSlice3AdmissionArtifactStore(path)
    store.seal(chain, now=NOW)
    if attack == "mode":
        path.chmod(0o600)
    elif attack == "hardlink":
        os.link(path, tmp_path / "second-link.json")
    else:
        path.chmod(0o600)
        raw = path.read_text(encoding="utf-8")
        path.write_text(
            raw.replace('"readiness":"allowed"', '"readiness":"blocked"'),
            encoding="utf-8",
        )
        path.chmod(0o400)

    with pytest.raises(Slice3AdmissionArtifactError):
        store.read(now=NOW, expected_chain_sha256=chain.chain_sha256)


def test_store_rejects_relative_path_and_symlink_target(tmp_path: Path) -> None:
    with pytest.raises(Slice3AdmissionArtifactError, match="path_invalid"):
        FileSlice3AdmissionArtifactStore(Path("relative.json"))

    target = tmp_path / "target.json"
    target.write_text("occupied", encoding="utf-8")
    symlink = tmp_path / "slice3-admission.json"
    symlink.symlink_to(target)
    store = FileSlice3AdmissionArtifactStore(symlink)
    with pytest.raises(Slice3AdmissionArtifactError, match="symlink"):
        store.seal(_chain(), now=NOW)


def test_production_store_is_fixed_and_module_has_no_live_surface() -> None:
    store = production_slice3_admission_store()
    assert store.path == SLICE3_ADMISSION_ARTIFACT_PATH
    assert store.path.is_absolute()
    forbidden = {
        "create_order",
        "cancel_order",
        "close_position",
        "preview_order",
        "register_route",
        "hydrate_client",
    }
    assert forbidden.isdisjoint(set(dir(admission_module)))
