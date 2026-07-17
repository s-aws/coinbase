from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import multiprocessing
from pathlib import Path
import stat
import threading
from types import SimpleNamespace
from uuid import UUID

import pytest

import api.v1.routes.futures as futures_routes
import application.admin_api.futures_order_preview_r12 as r12_module
from application.admin_api.futures_order_preview import (
    FUTURES_PREVIEW_PRODUCT_ID,
    canonical_json,
    canonical_sha256,
)
from application.admin_api.futures_order_preview_r12 import (
    FUTURES_PREVIEW_R12_ARTIFACT_TYPE,
    FUTURES_PREVIEW_R12_ELIGIBILITY_MARGIN_SOURCE_READS,
    FUTURES_PREVIEW_R12_PREDECESSOR_BINDING,
    FuturesPreviewR12ArtifactStore,
    FuturesPreviewR12AttemptClient,
    FuturesPreviewR12AttemptWorkflow,
    FuturesPreviewR12EligibilityClient,
    FuturesPreviewR12EligibilityError,
    FuturesPreviewR12EligibilityStore,
    FuturesPreviewR12EligibilityWorkflow,
    validate_production_futures_order_preview_r12_predecessor,
    validate_r12_margin_collateral_evidence,
)
from application.admin_api.models import AdminFuturesOrderPreviewR12Response


def _assert_r12_terminal_canonical_round_trip(
    terminal: dict[str, object],
) -> None:
    validated = AdminFuturesOrderPreviewR12Response.model_validate(terminal)
    serialized = validated.model_dump(mode="json")

    assert {
        "preview_response",
        "preview_response_sha256",
        "preview_id_sha256",
        "post_preview_stage_evidence_sha256",
    } <= terminal.keys()
    assert serialized == terminal
    assert canonical_sha256(
        {
            key: value
            for key, value in serialized.items()
            if key != "evidence_sha256"
        }
    ) == serialized["evidence_sha256"]


def _margin_snapshot() -> dict[str, object]:
    return {
        "status": "ready",
        "account_family": "coinbase_futures_us_cfm",
        "source": "backend_rest_client",
        "source_read_attempts": dict(
            FUTURES_PREVIEW_R12_ELIGIBILITY_MARGIN_SOURCE_READS
        ),
        "balance_summary": {
            "available_margin": {"value": "250.00", "currency": "USD"},
            "total_usd_balance": {"value": "500.00", "currency": "USD"},
            "cfm_usd_balance": {"value": "500.00", "currency": "USD"},
            "futures_buying_power": {"value": "1000.00", "currency": "USD"},
            "initial_margin": {"value": "40.00", "currency": "USD"},
            "liquidation_threshold": {"value": "80.00", "currency": "USD"},
            "intraday_margin_window_measure": {
                "margin_window_type": "FCM_MARGIN_WINDOW_TYPE_INTRADAY",
                "maintenance_margin": "20.00",
                "liquidation_buffer": "420.00",
            },
        },
        "intraday_margin_setting": {
            "setting": "INTRADAY_MARGIN_SETTING_INTRADAY",
        },
        "current_margin_windows": [
            {
                "profile": "MARGIN_PROFILE_TYPE_RETAIL_REGULAR",
                "status": "ready",
                "margin_window": {
                    "margin_window_type": "MARGIN_WINDOW_TYPE_UNSPECIFIED",
                },
                "is_intraday_margin_killswitch_enabled": False,
                "is_intraday_margin_enrollment_killswitch_enabled": False,
            },
            {
                "profile": "MARGIN_PROFILE_TYPE_RETAIL_INTRADAY_MARGIN_1",
                "status": "ready",
                "margin_window": {
                    "margin_window_type": "MARGIN_WINDOW_TYPE_INTRADAY",
                },
                "is_intraday_margin_killswitch_enabled": False,
                "is_intraday_margin_enrollment_killswitch_enabled": False,
            },
        ],
        "errors": [],
        "intx_applicability": "not_applicable_us_account",
    }


class _Delegate:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.sdk_client = _zero_retry_sdk_client()

    def get_sdk_client(self) -> object:
        return self.sdk_client

    def get_api_key_permissions(self) -> dict[str, object]:
        self.calls.append("get_api_key_permissions")
        return {}

    def list_portfolios(self) -> list[dict[str, object]]:
        self.calls.append("list_portfolios")
        return []

    def get_futures_preview_eligibility_portfolios(
        self,
    ) -> list[dict[str, object]]:
        return self.list_portfolios()

    def get_product_dict(self, product_id: str) -> dict[str, object]:
        assert product_id == FUTURES_PREVIEW_PRODUCT_ID
        self.calls.append("get_product_dict")
        return {}

    def get_best_bid_ask(self, *, product_ids: list[str]) -> dict[str, object]:
        assert product_ids == [FUTURES_PREVIEW_PRODUCT_ID]
        self.calls.append("get_best_bid_ask")
        return {}

    def get_futures_positions(self) -> dict[str, object]:
        self.calls.append("get_futures_positions")
        return {}

    def get_futures_preview_eligibility_margin_collateral_snapshot(
        self,
    ) -> dict[str, object]:
        self.calls.append(
            "get_futures_preview_eligibility_margin_collateral_snapshot"
        )
        return _margin_snapshot()

    def list_futures_sweeps(self) -> None:
        raise AssertionError("R12 eligibility must not call Futures sweeps")

    def preview_order(self, **_kwargs: object) -> None:
        raise AssertionError("R12 eligibility must not call Preview")


def _zero_retry_sdk_client() -> object:
    retry = SimpleNamespace(total=0)
    session = SimpleNamespace(
        adapters={
            "http://": SimpleNamespace(max_retries=retry),
            "https://": SimpleNamespace(max_retries=retry),
        },
        trust_env=False,
        verify=(
            "/usr/local/lib/python3.13/site-packages/certifi/cacert.pem"
        ),
        proxies={},
        max_redirects=0,
    )
    return SimpleNamespace(
        base_url="api.coinbase.com",
        timeout=30,
        rate_limit_headers=False,
        session=session,
    )


def test_r12_margin_validator_accepts_exact_v3_without_sweep_evidence() -> None:
    available = validate_r12_margin_collateral_evidence(_margin_snapshot())

    assert str(available) == "250.00"


def test_r12_margin_source_read_policy_is_immutable() -> None:
    with pytest.raises(TypeError):
        FUTURES_PREVIEW_R12_ELIGIBILITY_MARGIN_SOURCE_READS[
            "get_futures_balance_summary"
        ] = 2  # type: ignore[index]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value["source_read_attempts"].update(  # type: ignore[union-attr]
            list_futures_sweeps=1
        ),
        lambda value: value.update(futures_sweeps=[]),
        lambda value: value["current_margin_windows"][0][  # type: ignore[index]
            "margin_window"
        ].update(margin_window_type="MARGIN_WINDOW_TYPE_INTRADAY"),
        lambda value: value["source_read_attempts"].update(  # type: ignore[union-attr]
            get_futures_balance_summary=True
        ),
        lambda value: value["source_read_attempts"].pop(  # type: ignore[union-attr]
            "get_intraday_margin_setting"
        ),
        lambda value: value["current_margin_windows"].pop(),  # type: ignore[union-attr]
        lambda value: value.update(
            current_margin_windows=[
                deepcopy(value["current_margin_windows"][0]),  # type: ignore[index]
                deepcopy(value["current_margin_windows"][0]),  # type: ignore[index]
            ]
        ),
        lambda value: value["current_margin_windows"][0].update(  # type: ignore[index]
            is_intraday_margin_killswitch_enabled=True
        ),
        lambda value: value["current_margin_windows"][1].update(  # type: ignore[index]
            is_intraday_margin_enrollment_killswitch_enabled=True
        ),
        lambda value: value["current_margin_windows"][0].update(  # type: ignore[index]
            is_intraday_margin_killswitch_enabled=0
        ),
        lambda value: value["intraday_margin_setting"].update(  # type: ignore[union-attr]
            setting="INTRADAY_MARGIN_SETTING_UNSPECIFIED"
        ),
        lambda value: value["intraday_margin_setting"].update(  # type: ignore[union-attr]
            extra="forbidden"
        ),
        lambda value: value["balance_summary"]["available_margin"].update(  # type: ignore[index]
            currency="EUR"
        ),
        lambda value: value["balance_summary"]["available_margin"].update(  # type: ignore[index]
            value="0"
        ),
        lambda value: value["balance_summary"]["available_margin"].update(  # type: ignore[index]
            value="NaN"
        ),
        lambda value: value.update(errors=["withheld"]),
        lambda value: value.update(status="unknown"),
    ],
)
def test_r12_margin_validator_rejects_sweep_or_nonexact_v3_evidence(
    mutate,
) -> None:
    evidence = deepcopy(_margin_snapshot())
    mutate(evidence)

    with pytest.raises(ValueError):
        validate_r12_margin_collateral_evidence(evidence)


def test_r12_eligibility_client_cannot_be_constructed_without_started_cycle() -> None:
    delegate = _Delegate()

    with pytest.raises(
        FuturesPreviewR12EligibilityError,
        match="started cycle",
    ):
        FuturesPreviewR12EligibilityClient(delegate)

    assert delegate.calls == []


def test_r12_eligibility_store_reserves_nonattempt_cycles_without_claim_fields(
    tmp_path: Path,
) -> None:
    store = FuturesPreviewR12EligibilityStore(tmp_path / "eligibility.jsonl")
    correlation_id = "f56ad1da-1a82-4fc8-a5d6-79297c96535f"

    started = store.begin_cycle(
        correlation_id=correlation_id,
        started_at=datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc),
    )

    assert started["record_type"] == "eligibility_cycle_started"
    assert started["cycle_number"] == 1
    assert UUID(correlation_id).version == 4
    assert started["non_attempt_correlation_id"] == "withheld"
    assert started["non_attempt_correlation_id_sha256"] == hashlib.sha256(
        correlation_id.encode("utf-8")
    ).hexdigest()
    assert started["r12_claim_created"] is False
    assert started["r12_idempotency_key_created"] is False
    assert "claim" not in started
    assert "idempotency_key" not in started
    assert not (tmp_path / "futures_exact_no_live_preview_slice_2r12.jsonl").exists()
    observed = store.path.lstat()
    assert stat.S_ISREG(observed.st_mode)
    assert stat.S_IMODE(observed.st_mode) == 0o600
    assert observed.st_nlink == 1


def test_r12_eligibility_store_counts_started_unknown_cycles_toward_ten(
    tmp_path: Path,
) -> None:
    store = FuturesPreviewR12EligibilityStore(tmp_path / "eligibility.jsonl")

    for index in range(10):
        store.begin_cycle(
            correlation_id=f"00000000-0000-4000-8000-{index:012d}",
            started_at=datetime(2026, 7, 16, 12, index, tzinfo=timezone.utc),
        )

    assert store.cycle_count == 10
    assert FuturesPreviewR12EligibilityStore(store.path).cycle_count == 10
    with pytest.raises(ValueError, match="eligibility cycles exhausted"):
        store.begin_cycle(
            correlation_id="00000000-0000-4000-8000-000000000010",
            started_at=datetime(2026, 7, 16, 12, 10, tzinfo=timezone.utc),
        )


def test_r12_eligibility_store_rejects_duplicate_json_keys(tmp_path: Path) -> None:
    path = tmp_path / "eligibility.jsonl"
    path.write_text('{"record_type":"a","record_type":"b"}\n', encoding="utf-8")
    path.chmod(0o600)

    with pytest.raises(FuturesPreviewR12EligibilityError, match="invalid"):
        _ = FuturesPreviewR12EligibilityStore(path).cycle_count


def test_r12_workflow_lease_fails_closed_when_already_held(tmp_path: Path) -> None:
    first = FuturesPreviewR12EligibilityStore(tmp_path / "eligibility.jsonl")
    second = FuturesPreviewR12EligibilityStore(first.path)

    with first.workflow_lease():
        with pytest.raises(
            FuturesPreviewR12EligibilityError,
            match="already active",
        ):
            with second.workflow_lease():
                raise AssertionError("concurrent workflow lease was granted")


def test_r12_failed_nested_same_store_lease_preserves_outer_nonce(
    tmp_path: Path,
) -> None:
    store = FuturesPreviewR12EligibilityStore(
        tmp_path / "eligibility.jsonl"
    )

    with store.workflow_lease() as outer_nonce:
        store.require_active_workflow_lease(outer_nonce)
        with pytest.raises(
            FuturesPreviewR12EligibilityError,
            match="already active",
        ):
            with store.workflow_lease():
                raise AssertionError("nested workflow lease was granted")
        store.require_active_workflow_lease(outer_nonce)

    with pytest.raises(
        FuturesPreviewR12EligibilityError,
        match="active workflow lease",
    ):
        store.require_active_workflow_lease(outer_nonce)


def test_r12_workflow_thread_race_allows_only_one_active_reader(
    tmp_path: Path,
) -> None:
    path = tmp_path / "eligibility.jsonl"
    attempt_path = tmp_path / "attempt.jsonl"
    first_delegate = _ReadyDelegate(store_path=path)
    second_delegate = _ReadyDelegate(store_path=path)
    entered = threading.Event()
    release = threading.Event()
    original_read = first_delegate.get_api_key_permissions

    def blocking_read() -> dict[str, object]:
        entered.set()
        assert release.wait(timeout=5)
        return original_read()

    first_delegate.get_api_key_permissions = (  # type: ignore[method-assign]
        blocking_read
    )
    first = FuturesPreviewR12EligibilityWorkflow(
        store=FuturesPreviewR12EligibilityStore(path),
        attempt_artifact_path=attempt_path,
        rest_client_factory=lambda: first_delegate,
        now=lambda: datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc),
        correlation_id_factory=lambda: "a80bc8ba-b4d9-44fc-8772-8173ec3e9f65",
    )
    second = FuturesPreviewR12EligibilityWorkflow(
        store=FuturesPreviewR12EligibilityStore(path),
        attempt_artifact_path=attempt_path,
        rest_client_factory=lambda: second_delegate,
        now=lambda: datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc),
        correlation_id_factory=lambda: "24c08d06-6335-4c36-85b9-5fcc355cd3f4",
    )
    first_result: list[dict[str, object]] = []
    first_error: list[BaseException] = []

    def run_first() -> None:
        try:
            first_result.append(first.run_cycle())
        except BaseException as exc:  # pragma: no cover - asserted below
            first_error.append(exc)

    thread = threading.Thread(target=run_first)
    thread.start()
    assert entered.wait(timeout=5)
    try:
        with pytest.raises(
            FuturesPreviewR12EligibilityError,
            match="already active",
        ):
            second.run_cycle()
    finally:
        release.set()
        thread.join(timeout=5)

    assert not thread.is_alive()
    assert first_error == []
    assert first_result[0]["status"] == "eligible"
    assert second_delegate.calls == []
    assert FuturesPreviewR12EligibilityStore(path).cycle_count == 1


def test_r12_workflow_process_race_fails_closed(
    tmp_path: Path,
) -> None:
    path = tmp_path / "eligibility.jsonl"
    context = multiprocessing.get_context("fork")
    ready = context.Queue()
    release = context.Event()

    def hold_process_lease() -> None:
        with FuturesPreviewR12EligibilityStore(path).workflow_lease():
            ready.put("locked")
            if not release.wait(timeout=5):
                raise AssertionError("parent did not release child lease")

    process = context.Process(target=hold_process_lease)
    process.start()
    assert ready.get(timeout=5) == "locked"
    try:
        with pytest.raises(
            FuturesPreviewR12EligibilityError,
            match="already active",
        ):
            with FuturesPreviewR12EligibilityStore(path).workflow_lease():
                raise AssertionError("cross-process workflow lease was granted")
    finally:
        release.set()
        process.join(timeout=5)

    assert process.exitcode == 0


def test_r12_public_store_api_cannot_forge_eligible_completion(
    tmp_path: Path,
) -> None:
    store = FuturesPreviewR12EligibilityStore(tmp_path / "eligibility.jsonl")
    with store.workflow_lease() as lease_nonce:
        started = store.begin_cycle(
            correlation_id="2769973e-d5a6-4d93-9eab-805bd3a69caf",
            started_at=datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc),
        )
        with pytest.raises(
            FuturesPreviewR12EligibilityError,
            match="completion capability",
        ):
            store.complete_cycle(
                cycle_number=started["cycle_number"],
                completed_at=datetime(
                    2026, 7, 16, 12, 0, 1, tzinfo=timezone.utc
                ),
                outcome="eligible",
                classification="exact_v3_eligible",
                call_attempts={
                    category: 1
                    for category in r12_module._ELIGIBILITY_CATEGORIES
                },
                eligibility_evidence_sha256="1" * 64,
                _lease_nonce=lease_nonce,
            )


def _product() -> dict[str, object]:
    return {
        "product_id": FUTURES_PREVIEW_PRODUCT_ID,
        "display_name": "AVAX PERP",
        "product_type": "FUTURE",
        "status": "",
        "price": "6.47",
        "price_increment": "0.01",
        "base_increment": "1",
        "base_min_size": "1",
        "trading_disabled": False,
        "view_only": False,
        "cancel_only": False,
        "future_product_details": {
            "contract_size": "10",
            "contract_code": "AVP",
            "group_description": "Avalanche Perp Futures",
            "group_short_description": "Avalanche Perp",
            "venue": "cde",
            "risk_managed_by": "MANAGED_BY_FCM",
            "contract_expiry": "2030-12-20T16:00:00Z",
            "contract_expiry_type": "EXPIRING",
        },
    }


def _book() -> dict[str, object]:
    return {
        "pricebooks": [
            {
                "product_id": FUTURES_PREVIEW_PRODUCT_ID,
                "bids": [{"price": "6.46", "size": "8"}],
                "asks": [{"price": "6.48", "size": "9"}],
                "time": "2026-07-16T12:00:00Z",
            }
        ]
    }


class _ReadyDelegate(_Delegate):
    private_portfolio_id = "private-default-portfolio-id"

    def __init__(
        self,
        *,
        store_path: Path,
        margin: dict[str, object] | None = None,
        attempt_delegate: _AttemptDelegate | None = None,
    ):
        super().__init__()
        self.store_path = store_path
        self.margin = margin or _margin_snapshot()
        self.attempt_delegate = attempt_delegate

    def get_api_key_permissions(self) -> dict[str, object]:
        rows = self.store_path.read_text(encoding="utf-8").splitlines()
        assert rows
        assert json.loads(rows[-1])["record_type"] == (
            "eligibility_cycle_started"
        )
        self.calls.append("get_api_key_permissions")
        return {
            "portfolio_uuid": self.private_portfolio_id,
            "portfolio_type": "DEFAULT",
            "can_view": True,
            "can_trade": True,
            "private_secret": "must-never-persist",
        }

    def list_portfolios(self) -> list[dict[str, object]]:
        self.calls.append("list_portfolios")
        return [
            {
                "uuid": self.private_portfolio_id,
                "name": "Default",
                "type": "DEFAULT",
            }
        ]

    def get_product_dict(self, product_id: str) -> dict[str, object]:
        assert product_id == FUTURES_PREVIEW_PRODUCT_ID
        self.calls.append("get_product_dict")
        return _product()

    def get_best_bid_ask(self, *, product_ids: list[str]) -> dict[str, object]:
        assert product_ids == [FUTURES_PREVIEW_PRODUCT_ID]
        self.calls.append("get_best_bid_ask")
        return _book()

    def get_futures_positions(self) -> list[dict[str, object]]:
        self.calls.append("get_futures_positions")
        return []

    def get_futures_preview_eligibility_margin_collateral_snapshot(
        self,
    ) -> dict[str, object]:
        self.calls.append(
            "get_futures_preview_eligibility_margin_collateral_snapshot"
        )
        return deepcopy(self.margin)

    def preview_order(self, **kwargs: object) -> object:
        if self.attempt_delegate is None:
            raise AssertionError("Preview requires the integrated attempt fixture")
        return self.attempt_delegate.preview_order(**kwargs)


@pytest.mark.parametrize(
    ("reason", "expected"),
    [
        ("futures_preview_product_identity_blocked", "product_contract_ineligible"),
        ("futures_preview_avp_display_name_blocked", "product_contract_ineligible"),
        ("futures_preview_product_type_blocked", "product_contract_ineligible"),
        ("futures_preview_product_status_blocked", "product_contract_ineligible"),
        ("futures_preview_product_trading_blocked", "product_contract_ineligible"),
        (
            "futures_preview_avp_perp_style_identity_blocked",
            "product_contract_ineligible",
        ),
        ("futures_preview_contract_size_invalid", "product_contract_ineligible"),
        ("futures_preview_avp_contract_size_blocked", "product_contract_ineligible"),
        ("futures_preview_product_price_invalid", "product_contract_ineligible"),
        ("futures_preview_price_increment_invalid", "product_contract_ineligible"),
        ("futures_preview_base_increment_invalid", "product_contract_ineligible"),
        ("futures_preview_base_min_size_invalid", "product_contract_ineligible"),
        ("futures_preview_one_contract_rule_blocked", "product_contract_ineligible"),
        ("futures_preview_pricebook_missing", "market_book_ineligible"),
        ("futures_preview_pricebook_ambiguous", "market_book_ineligible"),
        ("futures_preview_market_time_missing", "market_book_ineligible"),
        ("futures_preview_market_time_invalid", "market_book_ineligible"),
        ("futures_preview_market_time_unzoned", "market_book_ineligible"),
        ("futures_preview_market_stale", "market_book_ineligible"),
        ("futures_preview_bids_missing", "market_book_ineligible"),
        ("futures_preview_bids_price_invalid", "market_book_ineligible"),
        ("futures_preview_asks_missing", "market_book_ineligible"),
        ("futures_preview_asks_price_invalid", "market_book_ineligible"),
        ("futures_preview_crossed_or_ambiguous_book", "market_book_ineligible"),
        ("futures_preview_best_bid_tick_misaligned", "market_book_ineligible"),
        ("futures_preview_limit_tick_blocked", "market_book_ineligible"),
        ("futures_preview_positions_ambiguous", "position_exposure_ineligible"),
        ("futures_preview_position_contracts_invalid", "position_exposure_ineligible"),
        (
            "futures_preview_existing_product_exposure_blocked",
            "position_exposure_ineligible",
        ),
        ("futures_preview_opening_cap_blocked", "candidate_caps_ineligible"),
        ("futures_preview_exposure_cap_blocked", "candidate_caps_ineligible"),
        ("futures_preview_buffered_close_cap_blocked", "candidate_caps_ineligible"),
        ("futures_preview_turnover_cap_blocked", "candidate_caps_ineligible"),
    ],
)
def test_r12_candidate_reason_classifier_is_exhaustive_and_value_blind(
    reason: str,
    expected: str,
) -> None:
    assert r12_module._candidate_failure_classification(ValueError(reason)) == (
        expected
    )


class _DerivedCandidateValueError(ValueError):
    pass


@pytest.mark.parametrize(
    "error",
    [
        RuntimeError("futures_preview_opening_cap_blocked"),
        _DerivedCandidateValueError("futures_preview_opening_cap_blocked"),
        ValueError("futures_preview_opening_cap_blocked", "second"),
        ValueError(123),
        ValueError("withheld-private-exception-text"),
    ],
)
def test_r12_candidate_reason_classifier_rejects_unknown_shapes(
    error: BaseException,
) -> None:
    assert r12_module._candidate_failure_classification(error) == (
        "internal_validation_blocked"
    )


def test_r12_eligibility_workflow_reserves_before_reads_and_returns_safe_success(
    tmp_path: Path,
) -> None:
    path = tmp_path / "eligibility.jsonl"
    delegate = _ReadyDelegate(store_path=path)
    workflow = FuturesPreviewR12EligibilityWorkflow(
        store=FuturesPreviewR12EligibilityStore(path),
        attempt_artifact_path=tmp_path / "attempt.jsonl",
        rest_client_factory=lambda: delegate,
        now=lambda: datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc),
        correlation_id_factory=lambda: "df4a5e3e-a227-4eb2-9980-1c6d2d2a7a34",
    )

    result = workflow.run_cycle()

    assert result["status"] == "eligible"
    assert result["classification"] == "exact_v3_eligible"
    assert result["cycle_number"] == 1
    assert result["r12_claim_created"] is False
    assert result["r12_idempotency_key_created"] is False
    assert result["eligibility_evidence"]["sweep_evidence"] == (
        "not_observed_not_authorized"
    )
    assert result["eligibility_evidence"]["read_counters"] == {
        "api_key_permissions": 1,
        "portfolio_catalog": 1,
        "product": 1,
        "best_bid_ask": 1,
        "futures_positions": 1,
        "futures_margin_collateral": 1,
    }
    assert delegate.calls == [
        "get_api_key_permissions",
        "list_portfolios",
        "get_product_dict",
        "get_best_bid_ask",
        "get_futures_positions",
        "get_futures_preview_eligibility_margin_collateral_snapshot",
    ]
    serialized = path.read_text(encoding="utf-8")
    assert _ReadyDelegate.private_portfolio_id not in serialized
    assert "must-never-persist" not in serialized
    assert "df4a5e3e-a227-4eb2-9980-1c6d2d2a7a34" not in serialized
    assert len(serialized.splitlines()) == 2
    assert not (tmp_path / "futures_exact_no_live_preview_slice_2r12.jsonl").exists()


@pytest.mark.parametrize(
    ("boundary", "expected_classification"),
    [
        ("product", "product_contract_ineligible"),
        ("market", "market_book_ineligible"),
        ("position", "position_exposure_ineligible"),
        ("caps", "candidate_caps_ineligible"),
    ],
)
def test_r12_eligibility_localizes_candidate_failure_without_values(
    tmp_path: Path,
    boundary: str,
    expected_classification: str,
) -> None:
    path = tmp_path / "eligibility.jsonl"
    delegate = _ReadyDelegate(store_path=path)
    if boundary in {"product", "caps"}:
        product = _product()
        if boundary == "product":
            product["status"] = "offline-private-value"
        else:
            product["price"] = "10"

        def get_product_dict(product_id: str) -> dict[str, object]:
            assert product_id == FUTURES_PREVIEW_PRODUCT_ID
            delegate.calls.append("get_product_dict")
            return deepcopy(product)

        delegate.get_product_dict = get_product_dict  # type: ignore[method-assign]
    elif boundary == "market":
        book = _book()
        book["pricebooks"][0]["time"] = "2026-07-16T11:00:00Z"  # type: ignore[index]

        def get_best_bid_ask(*, product_ids: list[str]) -> dict[str, object]:
            assert product_ids == [FUTURES_PREVIEW_PRODUCT_ID]
            delegate.calls.append("get_best_bid_ask")
            return deepcopy(book)

        delegate.get_best_bid_ask = get_best_bid_ask  # type: ignore[method-assign]
    else:

        def get_futures_positions() -> list[dict[str, object]]:
            delegate.calls.append("get_futures_positions")
            return [
                {
                    "product_id": FUTURES_PREVIEW_PRODUCT_ID,
                    "number_of_contracts": "1",
                }
            ]

        delegate.get_futures_positions = (  # type: ignore[method-assign]
            get_futures_positions
        )
    workflow = FuturesPreviewR12EligibilityWorkflow(
        store=FuturesPreviewR12EligibilityStore(path),
        attempt_artifact_path=tmp_path / "attempt.jsonl",
        rest_client_factory=lambda: delegate,
        now=lambda: datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc),
        correlation_id_factory=lambda: "62a5916c-d90c-440d-873e-dc4399ef1596",
    )

    result = workflow.run_cycle()

    assert result["status"] == "ineligible"
    assert result["classification"] == expected_classification
    serialized = path.read_text(encoding="utf-8")
    assert expected_classification in serialized
    assert "offline-private-value" not in serialized
    assert result["r12_claim_created"] is False
    assert result["r12_idempotency_key_created"] is False
    assert result["r12_attempt_consumed"] is False
    assert not (tmp_path / "attempt.jsonl").exists()


def test_r12_eligibility_unknown_candidate_reason_is_value_blind(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "eligibility.jsonl"
    delegate = _ReadyDelegate(store_path=path)
    monkeypatch.setattr(
        r12_module,
        "build_futures_order_preview_candidate",
        lambda **_kwargs: (_ for _ in ()).throw(
            ValueError("withheld-private-exception-text")
        ),
    )
    workflow = FuturesPreviewR12EligibilityWorkflow(
        store=FuturesPreviewR12EligibilityStore(path),
        attempt_artifact_path=tmp_path / "attempt.jsonl",
        rest_client_factory=lambda: delegate,
        now=lambda: datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc),
        correlation_id_factory=lambda: "7e9bb51a-bb6c-4c0e-b57b-4f9f6af4ef21",
    )

    result = workflow.run_cycle()

    assert result["status"] == "ineligible"
    assert result["classification"] == "internal_validation_blocked"
    assert "withheld-private-exception-text" not in repr(result)
    assert "withheld-private-exception-text" not in path.read_text(
        encoding="utf-8"
    )
    assert result["r12_attempt_consumed"] is False
    assert not (tmp_path / "attempt.jsonl").exists()


def test_r12_request_construction_cannot_reuse_candidate_classification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "eligibility.jsonl"
    delegate = _ReadyDelegate(store_path=path)
    monkeypatch.setattr(
        r12_module,
        "_preview_request",
        lambda _candidate: (_ for _ in ()).throw(
            ValueError("futures_preview_opening_cap_blocked")
        ),
    )
    workflow = FuturesPreviewR12EligibilityWorkflow(
        store=FuturesPreviewR12EligibilityStore(path),
        attempt_artifact_path=tmp_path / "attempt.jsonl",
        rest_client_factory=lambda: delegate,
        now=lambda: datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc),
        correlation_id_factory=lambda: "f6064f83-a4b7-40ec-a812-cf23e20b3011",
    )

    result = workflow.run_cycle()

    assert result["status"] == "ineligible"
    assert result["classification"] == "internal_validation_blocked"
    assert result["r12_attempt_consumed"] is False
    assert not (tmp_path / "attempt.jsonl").exists()


def test_r12_legacy_combined_failure_remains_readable_for_next_cycle(
    tmp_path: Path,
) -> None:
    path = tmp_path / "eligibility.jsonl"
    store = FuturesPreviewR12EligibilityStore(path)
    started = store.begin_cycle(
        correlation_id="106eb77f-a3a7-41d8-8fac-01d1c5a2108a",
        started_at=datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc),
    )
    attempts = {
        category: 1 for category in r12_module._ELIGIBILITY_CATEGORIES
    }
    with pytest.raises(FuturesPreviewR12EligibilityError, match="invalid"):
        store.complete_cycle(
            cycle_number=started["cycle_number"],
            completed_at=datetime(
                2026, 7, 16, 12, 0, 1, tzinfo=timezone.utc
            ),
            outcome="ineligible",
            classification="product_or_market_or_position_ineligible",
            call_attempts=attempts,
            eligibility_evidence_sha256=None,
        )
    legacy_completion = {
        "schema_version": "1",
        "record_type": "eligibility_cycle_completed",
        "cycle_number": 1,
        "started_record_sha256": started["record_sha256"],
        "completed_at": "2026-07-16T12:00:01Z",
        "outcome": "ineligible",
        "classification": "product_or_market_or_position_ineligible",
        "call_attempts": attempts,
        "margin_source_read_limits": dict(
            FUTURES_PREVIEW_R12_ELIGIBILITY_MARGIN_SOURCE_READS
        ),
        "eligibility_evidence_sha256": None,
        "r12_claim_created": False,
        "r12_idempotency_key_created": False,
        "r12_attempt_consumed": False,
        "raw_response_included": False,
        "external_exception_text_included": False,
        "private_identifier_values_included": False,
        "previous_record_sha256": started["record_sha256"],
    }
    legacy_completion["record_sha256"] = canonical_sha256(legacy_completion)
    with path.open("a", encoding="utf-8") as ledger:
        ledger.write(canonical_json(legacy_completion) + "\n")

    assert FuturesPreviewR12EligibilityStore(path).cycle_count == 1
    second = store.begin_cycle(
        correlation_id="4b65040c-e038-460a-bc46-7abdfd0eb093",
        started_at=datetime(2026, 7, 16, 12, 1, tzinfo=timezone.utc),
    )
    assert second["cycle_number"] == 2


def test_r12_eligibility_workflow_fails_closed_without_claim_on_nonexact_v3(
    tmp_path: Path,
) -> None:
    path = tmp_path / "eligibility.jsonl"
    margin = _margin_snapshot()
    margin["current_margin_windows"][0]["margin_window"][  # type: ignore[index]
        "margin_window_type"
    ] = "MARGIN_WINDOW_TYPE_OVERNIGHT"
    delegate = _ReadyDelegate(store_path=path, margin=margin)
    workflow = FuturesPreviewR12EligibilityWorkflow(
        store=FuturesPreviewR12EligibilityStore(path),
        attempt_artifact_path=tmp_path / "attempt.jsonl",
        rest_client_factory=lambda: delegate,
        now=lambda: datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc),
        correlation_id_factory=lambda: "4eef853c-70f0-46d5-8440-179c671b8252",
    )

    result = workflow.run_cycle()

    assert result == {
        "status": "ineligible",
        "classification": "margin_collateral_ineligible",
        "cycle_number": 1,
        "non_attempt_correlation_id": "withheld",
        "non_attempt_correlation_id_sha256": hashlib.sha256(
            b"4eef853c-70f0-46d5-8440-179c671b8252"
        ).hexdigest(),
        "r12_claim_created": False,
        "r12_idempotency_key_created": False,
        "r12_attempt_consumed": False,
    }
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
    ]
    assert all(row["record_type"] != "claim" for row in rows)
    assert all("idempotency_key" not in row for row in rows)


def test_r12_eligibility_workflow_withholds_delegate_exception_text(
    tmp_path: Path,
) -> None:
    path = tmp_path / "eligibility.jsonl"
    delegate = _ReadyDelegate(store_path=path)

    def unknown_read() -> None:
        delegate.calls.append("get_futures_positions")
        raise RuntimeError("private-exception-value")

    delegate.get_futures_positions = unknown_read  # type: ignore[method-assign]
    workflow = FuturesPreviewR12EligibilityWorkflow(
        store=FuturesPreviewR12EligibilityStore(path),
        attempt_artifact_path=tmp_path / "attempt.jsonl",
        rest_client_factory=lambda: delegate,
        now=lambda: datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc),
        correlation_id_factory=lambda: "8574f2f4-4d1d-4550-8ed3-3227805d604a",
    )

    result = workflow.run_cycle()

    assert result["status"] == "unknown"
    assert result["classification"] == "read_outcome_unknown"
    assert "private-exception-value" not in repr(result)
    assert "private-exception-value" not in path.read_text(encoding="utf-8")


def test_r12_eligibility_rejects_existing_attempt_before_any_factory(
    tmp_path: Path,
) -> None:
    eligibility_path = tmp_path / "eligibility.jsonl"
    attempt_path = tmp_path / "attempt.jsonl"
    attempt_path.write_text("claim-exists\n", encoding="utf-8")
    attempt_path.chmod(0o600)
    factory_calls = 0
    correlation_calls = 0

    def factory() -> object:
        nonlocal factory_calls
        factory_calls += 1
        raise AssertionError("factory must not run after claim material exists")

    def correlation() -> str:
        nonlocal correlation_calls
        correlation_calls += 1
        raise AssertionError("correlation must not be minted after claim")

    workflow = FuturesPreviewR12EligibilityWorkflow(
        store=FuturesPreviewR12EligibilityStore(eligibility_path),
        attempt_artifact_path=attempt_path,
        rest_client_factory=factory,
        now=lambda: datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc),
        correlation_id_factory=correlation,
    )

    with pytest.raises(FuturesPreviewR12EligibilityError, match="claimed"):
        workflow.run_cycle()

    assert factory_calls == 0
    assert correlation_calls == 0
    assert not eligibility_path.exists()


def test_r12_eligibility_rejects_non_attempt_workflow_callback_before_reads(
    tmp_path: Path,
) -> None:
    eligibility_path = tmp_path / "eligibility.jsonl"
    delegate = _ReadyDelegate(store_path=eligibility_path)
    workflow = FuturesPreviewR12EligibilityWorkflow(
        store=FuturesPreviewR12EligibilityStore(eligibility_path),
        attempt_artifact_path=tmp_path / "attempt.jsonl",
        rest_client_factory=lambda: delegate,
        now=lambda: datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc),
        correlation_id_factory=lambda: "78552d32-ed9c-4ab9-9261-17e8f1a2f0fb",
    )

    with pytest.raises(FuturesPreviewR12EligibilityError, match="attempt workflow"):
        workflow.run_cycle(attempt_workflow=lambda *_args: {})  # type: ignore[arg-type]

    assert delegate.calls == []
    assert not eligibility_path.exists()


def test_r12_eligibility_transport_retry_drift_fails_before_reads(
    tmp_path: Path,
) -> None:
    path = tmp_path / "eligibility.jsonl"
    delegate = _ReadyDelegate(store_path=path)
    delegate.sdk_client.session.adapters[  # type: ignore[attr-defined]
        "https://"
    ].max_retries.total = 1
    workflow = FuturesPreviewR12EligibilityWorkflow(
        store=FuturesPreviewR12EligibilityStore(path),
        attempt_artifact_path=tmp_path / "attempt.jsonl",
        rest_client_factory=lambda: delegate,
        now=lambda: datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc),
        correlation_id_factory=lambda: "0c7bed97-0511-47e7-8207-65e17be2b9c9",
    )

    result = workflow.run_cycle()

    assert result["status"] == "unknown"
    assert result["classification"] == "read_outcome_unknown"
    assert delegate.calls == []


def _preview_response() -> dict[str, object]:
    return {
        "preview_id": "private-preview-id",
        "errs": [],
        "warning": [],
        "order_total": "64.50",
        "commission_total": "0.12",
        "quote_size": "64.50",
        "base_size": "1",
        "best_bid": "6.46",
        "best_ask": "6.48",
        "order_margin_total": "10.00",
        "is_max": False,
        "margin_ratio_data": {
            "current_margin_ratio": "0.20",
            "projected_margin_ratio": "0.25",
        },
    }


class _AttemptDelegate:
    def __init__(self, *, artifact_path: Path, response: object | None = None):
        self.artifact_path = artifact_path
        self.response = response if response is not None else _preview_response()
        self.preview_calls: list[dict[str, object]] = []
        self.sdk_client = _zero_retry_sdk_client()

    def get_sdk_client(self) -> object:
        return self.sdk_client

    def preview_order(self, **kwargs: object) -> object:
        rows = self.artifact_path.read_text(encoding="utf-8").splitlines()
        assert len(rows) == 1
        claim = json.loads(rows[0])["record"]
        assert claim["artifact_type"] == FUTURES_PREVIEW_R12_ARTIFACT_TYPE
        assert claim["allowed_coinbase_methods"] == ["preview_order"]
        assert claim["correlation_id"] == "withheld"
        assert claim["idempotency_key"] == "withheld"
        assert len(claim["correlation_id_sha256"]) == 64
        assert len(claim["idempotency_key_sha256"]) == 64
        self.preview_calls.append(dict(kwargs))
        return self.response

    def get_api_key_permissions(self) -> None:
        raise AssertionError("attempt client cannot perform eligibility reads")

    def create_order(self, **_kwargs: object) -> None:
        raise AssertionError("attempt client cannot perform exchange mutations")


TEST_R12_PREDECESSOR_BINDING = deepcopy(
    FUTURES_PREVIEW_R12_PREDECESSOR_BINDING
)


def test_r12_predecessor_validation_keeps_restricted_generation_metadata_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, object, set[str]]] = []
    monkeypatch.setattr(
        r12_module,
        "validate_production_futures_order_preview_r7_opaque_chain",
        lambda: calls.append(("r1_r7", "chain", set())) or {},
    )

    def metadata_only(path: object, **kwargs: object) -> None:
        calls.append(("metadata_only", path, set(kwargs)))

    def opaque(path: object, **kwargs: object) -> None:
        calls.append(("opaque", path, set(kwargs)))

    monkeypatch.setattr(
        r12_module,
        "_validate_opaque_preview_artifact_metadata_only",
        metadata_only,
    )
    monkeypatch.setattr(
        r12_module,
        "_validate_opaque_preview_artifact",
        opaque,
    )

    binding = validate_production_futures_order_preview_r12_predecessor()

    assert binding == FUTURES_PREVIEW_R12_PREDECESSOR_BINDING
    assert "original_predecessor_binding" not in binding
    assert calls[0] == ("r1_r7", "chain", set())
    assert calls[1] == (
        "metadata_only",
        r12_module.FUTURES_PREVIEW_R8_ARTIFACT_PATH,
        {
            "expected_device",
            "expected_inode",
            "expected_size",
            "expected_mode",
            "expected_mtime_ns",
        },
    )
    assert [call[1] for call in calls[2:]] == [
        r12_module.FUTURES_PREVIEW_R9_ARTIFACT_PATH,
        r12_module.FUTURES_PREVIEW_R10_ARTIFACT_PATH,
        r12_module.FUTURES_PREVIEW_R11_ARTIFACT_PATH,
    ]
    assert all(
        call[2]
        == {
            "expected_file_sha256",
            "expected_device",
            "expected_inode",
            "expected_size",
            "expected_mode",
            "expected_mtime_ns",
        }
        for call in calls[2:]
    )


def _eligible_result(tmp_path: Path) -> dict[str, object]:
    eligibility_path = tmp_path / "eligibility.jsonl"
    delegate = _ReadyDelegate(store_path=eligibility_path)
    return FuturesPreviewR12EligibilityWorkflow(
        store=FuturesPreviewR12EligibilityStore(eligibility_path),
        attempt_artifact_path=tmp_path / "attempt.jsonl",
        rest_client_factory=lambda: delegate,
        now=lambda: datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc),
        correlation_id_factory=lambda: "fd5914b7-e2c6-40d7-a1b2-260514554aac",
    ).run_cycle()


def _attempt_workflow(
    tmp_path: Path,
    delegate: _AttemptDelegate,
    *,
    now: datetime = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc),
) -> tuple[FuturesPreviewR12AttemptWorkflow, FuturesPreviewR12ArtifactStore]:
    store = FuturesPreviewR12ArtifactStore(delegate.artifact_path)
    workflow = FuturesPreviewR12AttemptWorkflow(
        eligibility_store=FuturesPreviewR12EligibilityStore(
            tmp_path / "eligibility.jsonl"
        ),
        store=store,
        predecessor_binding=TEST_R12_PREDECESSOR_BINDING,
        predecessor_validator=lambda: dict(TEST_R12_PREDECESSOR_BINDING),
        now=lambda: now,
        correlation_id_factory=lambda: "540e6dc8-b5d8-40c4-96b8-b3119805c70e",
        idempotency_key_factory=lambda: "dbe48a6b-1cfe-4f63-abde-496c0544eef3",
    )
    return workflow, store


class _MultipleCycleReadyDelegate(_ReadyDelegate):
    """Ready fixture that accepts a prior incomplete non-attempt cycle."""

    def get_api_key_permissions(self) -> dict[str, object]:
        rows = self.store_path.read_text(encoding="utf-8").splitlines()
        assert len(rows) == 2
        assert json.loads(rows[-1])["record_type"] == (
            "eligibility_cycle_started"
        )
        self.calls.append("get_api_key_permissions")
        return {
            "portfolio_uuid": self.private_portfolio_id,
            "portfolio_type": "DEFAULT",
            "can_view": True,
            "can_trade": True,
            "private_secret": "must-never-persist",
        }


def _claimed_store_with_prior_incomplete_cycle(
    tmp_path: Path,
) -> tuple[
    FuturesPreviewR12EligibilityStore,
    dict[str, object],
    dict[str, object],
]:
    path = tmp_path / "eligibility.jsonl"
    store = FuturesPreviewR12EligibilityStore(path)
    incomplete = store.begin_cycle(
        correlation_id="7a0558e8-d1fd-47e1-8188-f8880f03623e",
        started_at=datetime(2026, 7, 16, 11, 59, tzinfo=timezone.utc),
    )
    delegate = _MultipleCycleReadyDelegate(store_path=path)
    eligible = FuturesPreviewR12EligibilityWorkflow(
        store=store,
        attempt_artifact_path=tmp_path / "attempt.jsonl",
        rest_client_factory=lambda: delegate,
        now=lambda: datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc),
        correlation_id_factory=lambda: (
            "87b95070-7521-45d5-9751-afedc7449c82"
        ),
    ).run_cycle()
    marker = store.mark_attempt_claimed(
        cycle_number=int(eligible["cycle_number"]),
        completion_record_sha256=str(
            eligible["eligibility_completion_record_sha256"]
        ),
        claim_record_sha256="2" * 64,
        claimed_at=datetime(2026, 7, 16, 12, 0, 1, tzinfo=timezone.utc),
    )
    return store, incomplete, marker


def test_r12_claim_marker_rejects_completion_of_prior_incomplete_cycle(
    tmp_path: Path,
) -> None:
    store, incomplete, _marker = _claimed_store_with_prior_incomplete_cycle(
        tmp_path
    )

    with pytest.raises(
        FuturesPreviewR12EligibilityError,
        match="completion is invalid",
    ):
        store.complete_cycle(
            cycle_number=int(incomplete["cycle_number"]),
            completed_at=datetime(
                2026, 7, 16, 12, 0, 2, tzinfo=timezone.utc
            ),
            outcome="unknown",
            classification="read_outcome_unknown",
            call_attempts={
                category: 0
                for category in r12_module._ELIGIBILITY_CATEGORIES
            },
            eligibility_evidence_sha256=None,
        )


def test_r12_ledger_parser_rejects_any_record_after_claim_marker(
    tmp_path: Path,
) -> None:
    store, incomplete, marker = _claimed_store_with_prior_incomplete_cycle(
        tmp_path
    )
    attacked: dict[str, object] = {
        "schema_version": "1",
        "record_type": "eligibility_cycle_completed",
        "cycle_number": incomplete["cycle_number"],
        "started_record_sha256": incomplete["record_sha256"],
        "completed_at": "2026-07-16T12:00:02Z",
        "outcome": "unknown",
        "classification": "read_outcome_unknown",
        "call_attempts": {
            category: 0
            for category in r12_module._ELIGIBILITY_CATEGORIES
        },
        "margin_source_read_limits": dict(
            FUTURES_PREVIEW_R12_ELIGIBILITY_MARGIN_SOURCE_READS
        ),
        "eligibility_evidence_sha256": None,
        "r12_claim_created": False,
        "r12_idempotency_key_created": False,
        "r12_attempt_consumed": False,
        "raw_response_included": False,
        "external_exception_text_included": False,
        "private_identifier_values_included": False,
        "previous_record_sha256": marker["record_sha256"],
    }
    attacked["record_sha256"] = canonical_sha256(attacked)
    with store.path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(r12_module.canonical_json(attacked) + "\n")

    with pytest.raises(
        FuturesPreviewR12EligibilityError,
        match="ledger is invalid",
    ):
        _ = FuturesPreviewR12EligibilityStore(store.path).cycle_count


def _recover_under_workflow_lease(
    workflow: FuturesPreviewR12AttemptWorkflow,
) -> dict[str, object] | None:
    with workflow.eligibility_store.workflow_lease() as lease_nonce:
        return workflow.recover_claim_only(_lease_nonce=lease_nonce)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("setting", "INTRADAY_MARGIN_SETTING_STANDARD"),
        ("measure", "FCM_MARGIN_WINDOW_TYPE_OVERNIGHT"),
        ("measure", "FCM_MARGIN_WINDOW_TYPE_WEEKEND"),
        ("measure", "FCM_MARGIN_WINDOW_TYPE_TRANSITION"),
    ],
)
def test_r12_nonexact_operational_margin_state_fails_before_claim_then_retries(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    eligibility_path = tmp_path / "eligibility.jsonl"
    attempt_path = tmp_path / "attempt.jsonl"
    attempt_delegate = _AttemptDelegate(artifact_path=attempt_path)
    invalid_margin = _margin_snapshot()
    if field == "setting":
        invalid_margin["intraday_margin_setting"]["setting"] = value  # type: ignore[index]
    else:
        invalid_margin["balance_summary"][  # type: ignore[index]
            "intraday_margin_window_measure"
        ]["margin_window_type"] = value
    invalid_delegate = _ReadyDelegate(
        store_path=eligibility_path,
        margin=invalid_margin,
        attempt_delegate=attempt_delegate,
    )
    valid_delegate = _ReadyDelegate(
        store_path=eligibility_path,
        attempt_delegate=attempt_delegate,
    )
    delegates = iter([invalid_delegate, valid_delegate])
    correlations = iter(
        [
            "f28be9eb-9df1-445a-8e9d-b16e6ca313a1",
            "6c73ef75-0c38-4ddb-9f86-aeadb3c5b967",
        ]
    )
    attempt, store = _attempt_workflow(tmp_path, attempt_delegate)
    eligibility = FuturesPreviewR12EligibilityWorkflow(
        store=attempt.eligibility_store,
        attempt_artifact_path=attempt_path,
        rest_client_factory=lambda: next(delegates),
        now=lambda: datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc),
        correlation_id_factory=lambda: next(correlations),
    )

    first = eligibility.run_cycle(attempt_workflow=attempt)

    assert first["status"] == "ineligible"
    assert first["classification"] == "margin_collateral_ineligible"
    assert first["cycle_number"] == 1
    assert first["r12_claim_created"] is False
    assert first["r12_idempotency_key_created"] is False
    assert first["r12_attempt_consumed"] is False
    assert not attempt_path.exists()
    assert attempt_delegate.preview_calls == []
    first_ledger = eligibility_path.read_text(encoding="utf-8")
    assert len(first_ledger.splitlines()) == 2
    first_rows = [json.loads(line) for line in first_ledger.splitlines()]
    assert all("idempotency_key" not in row for row in first_rows)
    assert all(row["record_type"] != "claim" for row in first_rows)

    terminal = eligibility.run_cycle(attempt_workflow=attempt)

    assert terminal["status"] == "accepted", (
        terminal,
        valid_delegate.calls,
    )
    assert terminal == store.read_completed()
    assert terminal["outcome"] == "accepted"
    assert terminal["non_attempt_eligibility"]["cycle_number"] == 2
    assert len(attempt_delegate.preview_calls) == 1


def test_r12_attempt_client_cannot_be_constructed_without_durable_claim(
    tmp_path: Path,
) -> None:
    class Delegate:
        def __init__(self) -> None:
            self.calls = 0

        def preview_order(self, **_kwargs: object) -> dict[str, object]:
            self.calls += 1
            return {}

    delegate = Delegate()
    with pytest.raises(
        FuturesPreviewR12EligibilityError,
        match="durable claim",
    ):
        FuturesPreviewR12AttemptClient(delegate)

    assert delegate.calls == 0


def test_r12_attempt_workflow_cannot_run_without_active_transition(
    tmp_path: Path,
) -> None:
    eligible = _eligible_result(tmp_path)
    attempt_path = tmp_path / "attempt.jsonl"
    delegate = _AttemptDelegate(artifact_path=attempt_path)
    workflow, _store = _attempt_workflow(tmp_path, delegate)

    with pytest.raises(
        FuturesPreviewR12EligibilityError,
        match="active eligibility transition",
    ):
        workflow.run(eligible)

    assert not attempt_path.exists()
    assert delegate.preview_calls == []


def test_r12_integrated_attempt_requires_exact_eligibility_store_instance(
    tmp_path: Path,
) -> None:
    eligibility_path = tmp_path / "eligibility.jsonl"
    attempt_path = tmp_path / "attempt.jsonl"
    delegate = _AttemptDelegate(artifact_path=attempt_path)
    attempt, _store = _attempt_workflow(tmp_path, delegate)
    factory_calls = 0

    def factory() -> object:
        nonlocal factory_calls
        factory_calls += 1
        return _ReadyDelegate(
            store_path=eligibility_path,
            attempt_delegate=delegate,
        )

    eligibility = FuturesPreviewR12EligibilityWorkflow(
        store=FuturesPreviewR12EligibilityStore(eligibility_path),
        attempt_artifact_path=attempt_path,
        rest_client_factory=factory,
        now=lambda: datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc),
        correlation_id_factory=lambda: "unused",
    )

    with pytest.raises(
        FuturesPreviewR12EligibilityError,
        match="store or path is invalid",
    ):
        eligibility.run_cycle(attempt_workflow=attempt)

    assert factory_calls == 0
    assert not eligibility_path.exists()
    assert not attempt_path.exists()


def test_r12_successful_eligibility_transitions_under_lease_to_one_preview(
    tmp_path: Path,
) -> None:
    eligibility_path = tmp_path / "eligibility.jsonl"
    attempt_path = tmp_path / "attempt.jsonl"
    attempt_delegate = _AttemptDelegate(artifact_path=attempt_path)
    eligibility_delegate = _ReadyDelegate(
        store_path=eligibility_path,
        attempt_delegate=attempt_delegate,
    )
    attempt, store = _attempt_workflow(tmp_path, attempt_delegate)
    eligibility = FuturesPreviewR12EligibilityWorkflow(
        store=attempt.eligibility_store,
        attempt_artifact_path=attempt_path,
        rest_client_factory=lambda: eligibility_delegate,
        now=lambda: datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc),
        correlation_id_factory=lambda: "cf28a20c-0472-49f7-87ee-ec2e8c4141fd",
    )

    terminal = eligibility.run_cycle(attempt_workflow=attempt)

    assert terminal == store.read_completed()
    assert terminal["artifact_type"] == FUTURES_PREVIEW_R12_ARTIFACT_TYPE
    assert terminal["status"] == terminal["outcome"] == "accepted"
    assert terminal["attempt_counters"] == {
        "preview_order": 1,
        "retry": 0,
        "fallback": 0,
        "create_order": 0,
        "cancel_order": 0,
        "close_position": 0,
        "reduce_position": 0,
    }
    assert terminal["post_claim_read_counters"] == {
        "api_key_permissions": 0,
        "portfolio_catalog": 0,
        "product": 0,
        "best_bid_ask": 0,
        "futures_positions": 0,
        "futures_margin_collateral": 0,
    }
    assert terminal["non_attempt_eligibility"]["status"] == "eligible"
    assert terminal["preview_response"]["preview_id"] == "withheld"
    assert len(terminal["preview_id_sha256"]) == 64
    assert "seal_ready_plan" not in terminal
    assert terminal["slice3_activation"] == "not_authorized"
    persisted = attempt_path.read_text(encoding="utf-8")
    assert "private-preview-id" not in persisted
    assert "540e6dc8-b5d8-40c4-96b8-b3119805c70e" not in persisted
    assert "dbe48a6b-1cfe-4f63-abde-496c0544eef3" not in persisted
    assert attempt_delegate.preview_calls == [
        {
            "product_id": FUTURES_PREVIEW_PRODUCT_ID,
            "side": "BUY",
            "order_configuration": {
                "limit_limit_gtc": {
                    "base_size": "1",
                    "limit_price": "6.45",
                    "post_only": True,
                }
            },
        }
    ]
    assert (
        AdminFuturesOrderPreviewR12Response.model_validate(terminal).outcome
        == "accepted"
    )
    _assert_r12_terminal_canonical_round_trip(terminal)


def test_r12_terminal_model_binds_preview_margin_to_available_margin(
    tmp_path: Path,
) -> None:
    eligibility_path = tmp_path / "eligibility.jsonl"
    attempt_path = tmp_path / "attempt.jsonl"
    attempt_delegate = _AttemptDelegate(artifact_path=attempt_path)
    attempt, _store = _attempt_workflow(tmp_path, attempt_delegate)
    eligibility = FuturesPreviewR12EligibilityWorkflow(
        store=attempt.eligibility_store,
        attempt_artifact_path=attempt_path,
        rest_client_factory=lambda: _ReadyDelegate(
            store_path=eligibility_path,
            attempt_delegate=attempt_delegate,
        ),
        now=lambda: datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc),
        correlation_id_factory=lambda: "7f2fd6e0-820c-4cb3-9fbf-f796f861d090",
    )
    terminal = eligibility.run_cycle(attempt_workflow=attempt)

    for order_margin_total in ("249.99", "250.00"):
        valid = deepcopy(terminal)
        valid["preview_response"]["order_margin_total"] = order_margin_total
        valid["preview_response_sha256"] = canonical_sha256(
            valid["preview_response"]
        )
        valid["evidence_sha256"] = canonical_sha256(
            {
                key: value
                for key, value in valid.items()
                if key != "evidence_sha256"
            }
        )
        assert (
            AdminFuturesOrderPreviewR12Response.model_validate(valid).outcome
            == "accepted"
        )

    invalid = deepcopy(terminal)
    invalid["preview_response"]["order_margin_total"] = "250.01"
    invalid["preview_response_sha256"] = canonical_sha256(
        invalid["preview_response"]
    )
    invalid["evidence_sha256"] = canonical_sha256(
        {
            key: value
            for key, value in invalid.items()
            if key != "evidence_sha256"
        }
    )
    with pytest.raises(
        ValueError,
        match="futures_preview_r12_accepted_evidence_invalid",
    ):
        AdminFuturesOrderPreviewR12Response.model_validate(invalid)


@pytest.mark.parametrize(
    ("field_group", "invalid_decimal"),
    [
        ("margin", "0E+1"),
        ("margin", "0." + ("0" * 127)),
        ("product", "1e0"),
        ("preview", "1e0"),
    ],
)
def test_r12_terminal_model_rejects_noncanonical_decimals_after_hash_rebinding(
    tmp_path: Path,
    field_group: str,
    invalid_decimal: str,
) -> None:
    eligibility_path = tmp_path / "eligibility.jsonl"
    attempt_path = tmp_path / "attempt.jsonl"
    attempt_delegate = _AttemptDelegate(artifact_path=attempt_path)
    attempt, _store = _attempt_workflow(tmp_path, attempt_delegate)
    eligibility = FuturesPreviewR12EligibilityWorkflow(
        store=attempt.eligibility_store,
        attempt_artifact_path=attempt_path,
        rest_client_factory=lambda: _ReadyDelegate(
            store_path=eligibility_path,
            attempt_delegate=attempt_delegate,
        ),
        now=lambda: datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc),
        correlation_id_factory=lambda: "27b09b91-23df-4164-94af-3f36577ce67d",
    )
    terminal = eligibility.run_cycle(attempt_workflow=attempt)
    invalid = deepcopy(terminal)
    eligibility_evidence = invalid["non_attempt_eligibility"]
    if field_group == "margin":
        margin_evidence = eligibility_evidence["margin_collateral_evidence"]
        margin_evidence["intraday_margin_window_measure"][
            "maintenance_margin_usdc"
        ] = invalid_decimal
        eligibility_evidence[
            "margin_collateral_evidence_sha256"
        ] = canonical_sha256(margin_evidence)
    elif field_group == "product":
        product_evidence = eligibility_evidence["product_evidence"]
        product_evidence["base_increment"] = invalid_decimal
        eligibility_evidence["product_evidence_sha256"] = canonical_sha256(
            product_evidence
        )
    else:
        invalid["preview_response"]["order_total"] = invalid_decimal
        invalid["preview_response_sha256"] = canonical_sha256(
            invalid["preview_response"]
        )
    if field_group != "preview":
        eligibility_evidence[
            "eligibility_evidence_sha256"
        ] = canonical_sha256(
            {
                key: value
                for key, value in eligibility_evidence.items()
                if key != "eligibility_evidence_sha256"
            }
        )
        invalid["non_attempt_eligibility_sha256"] = eligibility_evidence[
            "eligibility_evidence_sha256"
        ]
    invalid["evidence_sha256"] = canonical_sha256(
        {
            key: value
            for key, value in invalid.items()
            if key != "evidence_sha256"
        }
    )

    with pytest.raises(ValueError):
        AdminFuturesOrderPreviewR12Response.model_validate(invalid)


def test_r12_terminal_model_allows_only_fresh_market_observation_skew(
    tmp_path: Path,
) -> None:
    eligibility_path = tmp_path / "eligibility.jsonl"
    attempt_path = tmp_path / "attempt.jsonl"
    attempt_delegate = _AttemptDelegate(artifact_path=attempt_path)
    attempt, _store = _attempt_workflow(tmp_path, attempt_delegate)
    eligibility = FuturesPreviewR12EligibilityWorkflow(
        store=attempt.eligibility_store,
        attempt_artifact_path=attempt_path,
        rest_client_factory=lambda: _ReadyDelegate(
            store_path=eligibility_path,
            attempt_delegate=attempt_delegate,
        ),
        now=lambda: datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc),
        correlation_id_factory=lambda: "c3a7becd-1123-459c-800a-380aa72ea793",
    )
    terminal = eligibility.run_cycle(attempt_workflow=attempt)

    def with_market_skew(seconds: int) -> dict[str, object]:
        value = deepcopy(terminal)
        eligibility_evidence = value["non_attempt_eligibility"]
        candidate_observed = datetime.fromisoformat(
            eligibility_evidence["candidate"]["observed_at"].replace(
                "Z",
                "+00:00",
            )
        )
        exchange_observed = (
            candidate_observed - timedelta(seconds=seconds)
        ).isoformat(timespec="seconds").replace("+00:00", "Z")
        market = eligibility_evidence["market_evidence"]
        market["exchange_observed_at"] = exchange_observed
        eligibility_evidence["market_evidence_sha256"] = canonical_sha256(
            market
        )
        eligibility_evidence["eligibility_evidence_sha256"] = canonical_sha256(
            {
                key: item
                for key, item in eligibility_evidence.items()
                if key != "eligibility_evidence_sha256"
            }
        )
        value["non_attempt_eligibility_sha256"] = eligibility_evidence[
            "eligibility_evidence_sha256"
        ]
        value["evidence_sha256"] = canonical_sha256(
            {
                key: item
                for key, item in value.items()
                if key != "evidence_sha256"
            }
        )
        return value

    assert (
        AdminFuturesOrderPreviewR12Response.model_validate(
            with_market_skew(5)
        ).outcome
        == "accepted"
    )
    fractional_market = with_market_skew(1)
    fractional_eligibility = fractional_market["non_attempt_eligibility"]
    fractional_market_evidence = fractional_eligibility["market_evidence"]
    whole_exchange_observed = datetime.fromisoformat(
        fractional_market_evidence["exchange_observed_at"].replace(
            "Z",
            "+00:00",
        )
    )
    fractional_market_evidence["exchange_observed_at"] = (
        whole_exchange_observed.replace(microsecond=123456)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )
    fractional_eligibility["market_evidence_sha256"] = canonical_sha256(
        fractional_market_evidence
    )
    fractional_eligibility["eligibility_evidence_sha256"] = canonical_sha256(
        {
            key: item
            for key, item in fractional_eligibility.items()
            if key != "eligibility_evidence_sha256"
        }
    )
    fractional_market["non_attempt_eligibility_sha256"] = (
        fractional_eligibility["eligibility_evidence_sha256"]
    )
    fractional_market["evidence_sha256"] = canonical_sha256(
        {
            key: item
            for key, item in fractional_market.items()
            if key != "evidence_sha256"
        }
    )

    assert (
        AdminFuturesOrderPreviewR12Response.model_validate(
            fractional_market
        ).outcome
        == "accepted"
    )

    for invalid_market_timestamp in (
        "2026-07-16T11:59:59.12345Z",
        "2026-07-16T11:59:59.1234567Z",
        "2026-07-16T11:59:59.123456+00:00",
        "2026-02-30T11:59:59.123456Z",
    ):
        invalid_market = deepcopy(fractional_market)
        invalid_eligibility = invalid_market["non_attempt_eligibility"]
        invalid_market_evidence = invalid_eligibility["market_evidence"]
        invalid_market_evidence["exchange_observed_at"] = (
            invalid_market_timestamp
        )
        invalid_eligibility["market_evidence_sha256"] = canonical_sha256(
            invalid_market_evidence
        )
        invalid_eligibility["eligibility_evidence_sha256"] = canonical_sha256(
            {
                key: item
                for key, item in invalid_eligibility.items()
                if key != "eligibility_evidence_sha256"
            }
        )
        invalid_market["non_attempt_eligibility_sha256"] = (
            invalid_eligibility["eligibility_evidence_sha256"]
        )
        invalid_market["evidence_sha256"] = canonical_sha256(
            {
                key: item
                for key, item in invalid_market.items()
                if key != "evidence_sha256"
            }
        )
        with pytest.raises(
            ValueError,
            match="futures_preview_r12_timestamp_invalid",
        ):
            AdminFuturesOrderPreviewR12Response.model_validate(invalid_market)

    fractional_internal = deepcopy(terminal)
    reserved = datetime.fromisoformat(
        fractional_internal["reserved_at"].replace("Z", "+00:00")
    )
    fractional_internal["reserved_at"] = (
        reserved.replace(microsecond=123456)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )
    fractional_internal["completed_at"] = (
        (reserved + timedelta(seconds=1))
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )
    fractional_internal["evidence_sha256"] = canonical_sha256(
        {
            key: item
            for key, item in fractional_internal.items()
            if key != "evidence_sha256"
        }
    )
    with pytest.raises(
        ValueError,
        match="futures_preview_r12_timestamp_invalid",
    ):
        AdminFuturesOrderPreviewR12Response.model_validate(
            fractional_internal
        )

    with pytest.raises(
        ValueError,
        match="futures_preview_r12_candidate_invalid",
    ):
        AdminFuturesOrderPreviewR12Response.model_validate(
            with_market_skew(31)
        )


def test_r12_claim_closes_all_later_eligibility_before_reads(
    tmp_path: Path,
) -> None:
    eligibility_path = tmp_path / "eligibility.jsonl"
    attempt_path = tmp_path / "attempt.jsonl"
    attempt_delegate = _AttemptDelegate(artifact_path=attempt_path)
    first_delegate = _ReadyDelegate(
        store_path=eligibility_path,
        attempt_delegate=attempt_delegate,
    )
    attempt, _store = _attempt_workflow(tmp_path, attempt_delegate)
    first = FuturesPreviewR12EligibilityWorkflow(
        store=attempt.eligibility_store,
        attempt_artifact_path=attempt_path,
        rest_client_factory=lambda: first_delegate,
        now=lambda: datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc),
        correlation_id_factory=lambda: "94ad872e-f9e1-4e76-b01f-a6325e493e5a",
    )
    first.run_cycle(attempt_workflow=attempt)
    second_factory_calls = 0

    def second_factory() -> object:
        nonlocal second_factory_calls
        second_factory_calls += 1
        raise AssertionError("no post-claim eligibility delegate is allowed")

    second = FuturesPreviewR12EligibilityWorkflow(
        store=FuturesPreviewR12EligibilityStore(eligibility_path),
        attempt_artifact_path=attempt_path,
        rest_client_factory=second_factory,
        now=lambda: datetime(2026, 7, 16, 12, 0, 1, tzinfo=timezone.utc),
        correlation_id_factory=lambda: "11c029ee-4990-4d61-8905-b786f4d31542",
    )

    with pytest.raises(FuturesPreviewR12EligibilityError, match="claimed"):
        second.run_cycle()

    assert second_factory_calls == 0
    assert len(attempt_delegate.preview_calls) == 1


def test_r12_tampered_preview_request_cannot_create_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    eligibility_path = tmp_path / "eligibility.jsonl"
    attempt_path = tmp_path / "attempt.jsonl"
    delegate = _AttemptDelegate(artifact_path=attempt_path)
    attempt, _store = _attempt_workflow(tmp_path, delegate)
    original_builder = r12_module._r12_eligibility_evidence

    def tampered_builder(**kwargs: object) -> dict[str, object]:
        evidence = original_builder(**kwargs)  # type: ignore[arg-type]
        evidence["preview_request"]["order_configuration"][  # type: ignore[index]
            "limit_limit_gtc"
        ]["base_size"] = "2"
        evidence["preview_request_sha256"] = canonical_sha256(
            evidence["preview_request"]
        )
        evidence["eligibility_evidence_sha256"] = canonical_sha256(
            {
                key: value
                for key, value in evidence.items()
                if key != "eligibility_evidence_sha256"
            }
        )
        return evidence

    monkeypatch.setattr(
        r12_module,
        "_r12_eligibility_evidence",
        tampered_builder,
    )
    eligibility = FuturesPreviewR12EligibilityWorkflow(
        store=attempt.eligibility_store,
        attempt_artifact_path=attempt_path,
        rest_client_factory=lambda: _ReadyDelegate(
            store_path=eligibility_path,
            attempt_delegate=delegate,
        ),
        now=lambda: datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc),
        correlation_id_factory=lambda: "20894b6c-6521-4630-b6d3-8e61cb169370",
    )

    with pytest.raises(FuturesPreviewR12EligibilityError, match="invalid"):
        eligibility.run_cycle(attempt_workflow=attempt)

    assert not attempt_path.exists()
    assert delegate.preview_calls == []


def test_r12_restart_recovers_claim_only_without_coinbase_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    eligibility_path = tmp_path / "eligibility.jsonl"
    attempt_path = tmp_path / "attempt.jsonl"
    attempt_delegate = _AttemptDelegate(artifact_path=attempt_path)
    attempt, store = _attempt_workflow(tmp_path, attempt_delegate)
    ready_delegate = _ReadyDelegate(
        store_path=eligibility_path,
        attempt_delegate=attempt_delegate,
    )

    def fractional_best_bid_ask(
        *,
        product_ids: list[str],
    ) -> dict[str, object]:
        assert product_ids == [FUTURES_PREVIEW_PRODUCT_ID]
        ready_delegate.calls.append("get_best_bid_ask")
        result = _book()
        result["pricebooks"][0]["time"] = "2026-07-16T12:00:00.123456Z"
        return result

    ready_delegate.get_best_bid_ask = (  # type: ignore[method-assign]
        fractional_best_bid_ask
    )

    def crash_after_claim(**_kwargs: object) -> None:
        raise SystemExit("synthetic-process-crash-after-claim")

    monkeypatch.setattr(
        attempt.eligibility_store,
        "mark_attempt_claimed",
        crash_after_claim,
    )
    eligibility = FuturesPreviewR12EligibilityWorkflow(
        store=attempt.eligibility_store,
        attempt_artifact_path=attempt_path,
        rest_client_factory=lambda: ready_delegate,
        now=lambda: datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc),
        correlation_id_factory=lambda: "e5bd9216-7547-4c5b-8d22-90775977bd09",
    )

    with pytest.raises(SystemExit, match="synthetic-process-crash"):
        eligibility.run_cycle(attempt_workflow=attempt)

    assert len(attempt_path.read_text(encoding="utf-8").splitlines()) == 1
    assert attempt_delegate.preview_calls == []
    recovery = FuturesPreviewR12AttemptWorkflow(
        eligibility_store=FuturesPreviewR12EligibilityStore(eligibility_path),
        store=store,
        predecessor_binding=TEST_R12_PREDECESSOR_BINDING,
        predecessor_validator=lambda: dict(TEST_R12_PREDECESSOR_BINDING),
        now=lambda: datetime(2026, 7, 16, 12, 1, tzinfo=timezone.utc),
        correlation_id_factory=lambda: (_ for _ in ()).throw(
            AssertionError("recovery must not mint correlation material")
        ),
        idempotency_key_factory=lambda: (_ for _ in ()).throw(
            AssertionError("recovery must not mint idempotency material")
        ),
    )

    with pytest.raises(
        FuturesPreviewR12EligibilityError,
        match="active workflow lease",
    ):
        recovery.recover_claim_only()
    assert len(attempt_path.read_text(encoding="utf-8").splitlines()) == 1

    terminal = _recover_under_workflow_lease(recovery)

    assert terminal is not None
    assert terminal["status"] == terminal["outcome"] == "unknown"
    assert terminal["blocker"] == "claim_only_recovery_unknown_consumed"
    assert terminal["attempt_counters"]["preview_order"] == 1
    assert attempt_delegate.preview_calls == []
    assert _recover_under_workflow_lease(recovery) == terminal
    assert (
        AdminFuturesOrderPreviewR12Response.model_validate(terminal).outcome
        == "unknown"
    )
    _assert_r12_terminal_canonical_round_trip(terminal)


def test_r12_restart_after_preview_append_crash_never_retries_preview(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    eligibility_path = tmp_path / "eligibility.jsonl"
    attempt_path = tmp_path / "attempt.jsonl"
    attempt_delegate = _AttemptDelegate(artifact_path=attempt_path)
    attempt, store = _attempt_workflow(tmp_path, attempt_delegate)

    def crash_before_terminal(
        _terminal: object,
        **_kwargs: object,
    ) -> None:
        raise SystemExit("synthetic-process-crash-before-terminal")

    monkeypatch.setattr(attempt, "_append_terminal", crash_before_terminal)
    eligibility = FuturesPreviewR12EligibilityWorkflow(
        store=attempt.eligibility_store,
        attempt_artifact_path=attempt_path,
        rest_client_factory=lambda: _ReadyDelegate(
            store_path=eligibility_path,
            attempt_delegate=attempt_delegate,
        ),
        now=lambda: datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc),
        correlation_id_factory=lambda: "c2d04609-7bb1-4761-b663-b2db539da786",
    )

    with pytest.raises(SystemExit, match="synthetic-process-crash"):
        eligibility.run_cycle(attempt_workflow=attempt)

    assert len(attempt_delegate.preview_calls) == 1
    assert len(attempt_path.read_text(encoding="utf-8").splitlines()) == 1
    recovery = FuturesPreviewR12AttemptWorkflow(
        eligibility_store=FuturesPreviewR12EligibilityStore(eligibility_path),
        store=store,
        predecessor_binding=TEST_R12_PREDECESSOR_BINDING,
        predecessor_validator=lambda: dict(TEST_R12_PREDECESSOR_BINDING),
        now=lambda: datetime(2026, 7, 16, 12, 1, tzinfo=timezone.utc),
        correlation_id_factory=lambda: "unused",
        idempotency_key_factory=lambda: "unused",
    )

    terminal = _recover_under_workflow_lease(recovery)

    assert terminal is not None
    assert terminal["blocker"] == "claim_only_recovery_unknown_consumed"
    assert terminal["attempt_counters"]["preview_order"] == 1
    assert len(attempt_delegate.preview_calls) == 1


@pytest.mark.parametrize(
    "mutate",
    [
        lambda terminal: terminal.update(correlation_id="raw-private-id"),
        lambda terminal: terminal["attempt_counters"].update(retry=1),
        lambda terminal: terminal["eligibility_read_counters"].update(
            product=True
        ),
        lambda terminal: terminal["non_attempt_eligibility"].update(
            sweep_evidence="observed"
        ),
        lambda terminal: terminal["non_attempt_eligibility"].update(
            non_attempt_correlation_id="raw-private-id"
        ),
        lambda terminal: terminal["non_attempt_eligibility"][
            "permission_evidence"
        ].update(unexpected_private_field="raw-private-id"),
        lambda terminal: terminal["non_attempt_eligibility"][
            "permission_evidence"
        ].update(can_view=1),
        lambda terminal: terminal["non_attempt_eligibility"][
            "portfolio_binding"
        ].update(portfolio_id="raw-private-id"),
        lambda terminal: terminal["non_attempt_eligibility"][
            "candidate"
        ].update(unexpected_candidate_field="raw-private-id"),
        lambda terminal: terminal["candidate"].update(
            unexpected_candidate_field="raw-private-id"
        ),
        lambda terminal: (
            terminal["non_attempt_eligibility"]["preview_request"][
                "order_configuration"
            ]["limit_limit_gtc"].update(post_only=1),
            terminal["preview_request"]["order_configuration"][
                "limit_limit_gtc"
            ].update(post_only=1),
        ),
        lambda terminal: terminal.update(seal_ready_plan={}),
    ],
)
def test_r12_readback_model_rejects_privacy_authority_or_sweep_drift(
    tmp_path: Path,
    mutate,
) -> None:
    eligibility_path = tmp_path / "eligibility.jsonl"
    attempt_path = tmp_path / "attempt.jsonl"
    attempt_delegate = _AttemptDelegate(artifact_path=attempt_path)
    attempt, _store = _attempt_workflow(tmp_path, attempt_delegate)
    terminal = FuturesPreviewR12EligibilityWorkflow(
        store=attempt.eligibility_store,
        attempt_artifact_path=attempt_path,
        rest_client_factory=lambda: _ReadyDelegate(
            store_path=eligibility_path,
            attempt_delegate=attempt_delegate,
        ),
        now=lambda: datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc),
        correlation_id_factory=lambda: "033feded-a32c-45b5-9af0-3fb70c947917",
    ).run_cycle(attempt_workflow=attempt)
    candidate = deepcopy(terminal)
    mutate(candidate)
    if isinstance(candidate.get("non_attempt_eligibility"), dict):
        eligibility = candidate["non_attempt_eligibility"]
        for evidence_field, hash_field in (
            ("permission_evidence", "permission_evidence_sha256"),
            (
                "portfolio_catalog_evidence",
                "portfolio_catalog_evidence_sha256",
            ),
            ("product_evidence", "product_evidence_sha256"),
            ("market_evidence", "market_evidence_sha256"),
            ("position_evidence", "position_evidence_sha256"),
            (
                "margin_collateral_evidence",
                "margin_collateral_evidence_sha256",
            ),
            (
                "margin_window_policy_evidence",
                "margin_window_policy_evidence_sha256",
            ),
            (
                "transport_policy_evidence",
                "transport_policy_evidence_sha256",
            ),
            ("candidate", "candidate_sha256"),
            ("preview_request", "preview_request_sha256"),
        ):
            if isinstance(eligibility.get(evidence_field), dict):
                eligibility[hash_field] = canonical_sha256(
                    eligibility[evidence_field]
                )
        eligibility["eligibility_evidence_sha256"] = canonical_sha256(
            {
                key: value
                for key, value in eligibility.items()
                if key != "eligibility_evidence_sha256"
            }
        )
        candidate["non_attempt_eligibility_sha256"] = eligibility[
            "eligibility_evidence_sha256"
        ]
    if isinstance(candidate.get("candidate"), dict):
        candidate["candidate_sha256"] = canonical_sha256(
            candidate["candidate"]
        )
    if isinstance(candidate.get("preview_request"), dict):
        candidate["preview_request_sha256"] = canonical_sha256(
            candidate["preview_request"]
        )
    candidate["evidence_sha256"] = canonical_sha256(
        {
            key: value
            for key, value in candidate.items()
            if key != "evidence_sha256"
        }
    )

    with pytest.raises(ValueError):
        AdminFuturesOrderPreviewR12Response.model_validate(candidate)


def test_r12_stale_eligibility_cannot_create_claim(tmp_path: Path) -> None:
    eligibility_path = tmp_path / "eligibility.jsonl"
    attempt_path = tmp_path / "attempt.jsonl"
    delegate = _AttemptDelegate(artifact_path=attempt_path)
    workflow, _store = _attempt_workflow(
        tmp_path,
        delegate,
        now=datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)
        + timedelta(seconds=11),
    )
    eligibility = FuturesPreviewR12EligibilityWorkflow(
        store=workflow.eligibility_store,
        attempt_artifact_path=attempt_path,
        rest_client_factory=lambda: _ReadyDelegate(
            store_path=eligibility_path,
            attempt_delegate=delegate,
        ),
        now=lambda: datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc),
        correlation_id_factory=lambda: "d27fa0c7-e7df-431a-bddf-ea0922996fc9",
    )

    with pytest.raises(FuturesPreviewR12EligibilityError, match="stale"):
        eligibility.run_cycle(attempt_workflow=workflow)

    assert not attempt_path.exists()
    assert delegate.preview_calls == []


def test_r12_preview_exception_is_unknown_consumed_without_retry(
    tmp_path: Path,
) -> None:
    eligibility_path = tmp_path / "eligibility.jsonl"
    attempt_path = tmp_path / "attempt.jsonl"
    delegate = _AttemptDelegate(artifact_path=attempt_path)

    def unknown_preview(**kwargs: object) -> object:
        delegate.preview_calls.append(dict(kwargs))
        raise RuntimeError("private-preview-exception")

    delegate.preview_order = unknown_preview  # type: ignore[method-assign]
    workflow, store = _attempt_workflow(tmp_path, delegate)
    eligibility = FuturesPreviewR12EligibilityWorkflow(
        store=workflow.eligibility_store,
        attempt_artifact_path=attempt_path,
        rest_client_factory=lambda: _ReadyDelegate(
            store_path=eligibility_path,
            attempt_delegate=delegate,
        ),
        now=lambda: datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc),
        correlation_id_factory=lambda: "b5b17657-f4c7-4266-95d7-3ca573b26493",
    )

    with pytest.raises(FuturesPreviewR12EligibilityError, match="consumed"):
        eligibility.run_cycle(attempt_workflow=workflow)

    terminal = store.read_completed()
    assert terminal["status"] == terminal["outcome"] == "unknown"
    assert terminal["blocker"] == "preview_order_unknown_consumed"
    assert terminal["attempt_counters"]["preview_order"] == 1
    assert (
        AdminFuturesOrderPreviewR12Response.model_validate(terminal).outcome
        == "unknown"
    )
    invalid = deepcopy(terminal)
    invalid["attempt_counters"]["preview_order"] = 0
    invalid["evidence_sha256"] = canonical_sha256(
        {
            key: value
            for key, value in invalid.items()
            if key != "evidence_sha256"
        }
    )
    with pytest.raises(ValueError):
        AdminFuturesOrderPreviewR12Response.model_validate(invalid)
    recovered = deepcopy(terminal)
    recovered["blocker"] = "claim_only_recovery_unknown_consumed"
    recovered["evidence_sha256"] = canonical_sha256(
        {
            key: value
            for key, value in recovered.items()
            if key != "evidence_sha256"
        }
    )
    assert (
        AdminFuturesOrderPreviewR12Response.model_validate(recovered).outcome
        == "unknown"
    )
    assert len(delegate.preview_calls) == 1
    assert "private-preview-exception" not in attempt_path.read_text(
        encoding="utf-8"
    )


def test_r12_terminal_predecessor_change_persists_precise_blocked_terminal(
    tmp_path: Path,
) -> None:
    eligibility_path = tmp_path / "eligibility.jsonl"
    attempt_path = tmp_path / "attempt.jsonl"
    delegate = _AttemptDelegate(artifact_path=attempt_path)
    workflow, store = _attempt_workflow(tmp_path, delegate)
    predecessor_calls = 0

    def predecessor_validator() -> dict[str, object]:
        nonlocal predecessor_calls
        predecessor_calls += 1
        if predecessor_calls < 3:
            return dict(TEST_R12_PREDECESSOR_BINDING)
        changed = dict(TEST_R12_PREDECESSOR_BINDING)
        changed["mtime_ns"] = int(changed["mtime_ns"]) + 1
        return changed

    workflow.predecessor_validator = predecessor_validator
    eligibility = FuturesPreviewR12EligibilityWorkflow(
        store=workflow.eligibility_store,
        attempt_artifact_path=attempt_path,
        rest_client_factory=lambda: _ReadyDelegate(
            store_path=eligibility_path,
            attempt_delegate=delegate,
        ),
        now=lambda: datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc),
        correlation_id_factory=lambda: "d6a15c31-5b30-4c37-ae68-a427f1bc02f7",
    )

    with pytest.raises(
        FuturesPreviewR12EligibilityError,
        match="terminal validation blocked; attempt consumed",
    ):
        eligibility.run_cycle(attempt_workflow=workflow)

    terminal = store.read_completed()
    assert predecessor_calls == 3
    assert len(delegate.preview_calls) == 1
    assert terminal["status"] == terminal["outcome"] == "blocked"
    assert terminal["blocker"] == "terminal_predecessor_validation_blocked"
    assert terminal["post_preview_stage_evidence"]["stages"] == [
        {
            "stage": "terminal_predecessor_validation",
            "status": "blocked",
            "reason_code": "futures_preview_terminal_predecessor_blocked",
        }
    ]
    assert (
        AdminFuturesOrderPreviewR12Response.model_validate(terminal).outcome
        == "blocked"
    )
    _assert_r12_terminal_canonical_round_trip(terminal)


def test_r12_converter_only_response_is_blocked_without_conversion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ConverterOnly:
        converter_called = False

        def to_dict(self) -> dict[str, object]:
            type(self).converter_called = True
            raise AssertionError("converter-only response must not be traversed")

    eligibility_path = tmp_path / "eligibility.jsonl"
    attempt_path = tmp_path / "attempt.jsonl"
    delegate = _AttemptDelegate(
        artifact_path=attempt_path,
        response=ConverterOnly(),
    )
    workflow, store = _attempt_workflow(tmp_path, delegate)
    eligibility = FuturesPreviewR12EligibilityWorkflow(
        store=workflow.eligibility_store,
        attempt_artifact_path=attempt_path,
        rest_client_factory=lambda: _ReadyDelegate(
            store_path=eligibility_path,
            attempt_delegate=delegate,
        ),
        now=lambda: datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc),
        correlation_id_factory=lambda: "85e62da0-3204-435e-8bdc-239c6c7710b8",
    )

    with pytest.raises(FuturesPreviewR12EligibilityError, match="consumed"):
        eligibility.run_cycle(attempt_workflow=workflow)

    terminal = store.read_completed()
    assert terminal["status"] == terminal["outcome"] == "blocked"
    assert terminal["post_preview_stage_evidence"]["stages"] == [
        {
            "stage": "preview_response_validation",
            "status": "blocked",
            "reason_code": "futures_preview_response_validation_blocked",
        }
    ]
    assert (
        AdminFuturesOrderPreviewR12Response.model_validate(terminal).outcome
        == "blocked"
    )
    _assert_r12_terminal_canonical_round_trip(terminal)
    monkeypatch.setattr(futures_routes, "require_permission", lambda *_: None)
    response = futures_routes.get_futures_order_preview(
        actor=object(),
        store=store,
    )
    response_payload = json.loads(response.body)
    assert response_payload == terminal
    assert canonical_sha256(
        {
            key: value
            for key, value in response_payload.items()
            if key != "evidence_sha256"
        }
    ) == response_payload["evidence_sha256"]
    assert ConverterOnly.converter_called is False
