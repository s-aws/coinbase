from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest

from application.admin_api.operator_spot_order_truth import (
    SPOT_ORDER_TRUTH_GOAL_ID,
    SpotOrderCatalogReader,
    SpotOrderCatalogResult,
    SpotOrderObservation,
    _normalize_order,
)
from application.admin_api.operator_spot_order_truth_service import (
    OperatorSpotOrderTruthService,
    SpotOrderTruthGoalRecord,
    SpotOrderTruthRequestContext,
)
from application.admin_api.operator_spot_order_truth_models import (
    OperatorSpotOrderTruthReadback,
)


def _context(*, cancel: bool = False) -> SpotOrderTruthRequestContext:
    return SpotOrderTruthRequestContext(
        actor_id="operator-1",
        roles=("operator",),
        expected_revision=0,
        idempotency_key="idem-1",
        correlation_id="correlation-1",
        audit_id="audit-1",
        operator_intent=(
            "cancel_exact_spot_order" if cancel else "refresh_spot_order_truth"
        ),
        authorize_one_no_retry_cycle=True,
        acknowledge_cycle_is_goal_global_and_limited_to_one=True,
        acknowledge_unknown_read_fails_closed=True,
        acknowledge_unknown_cancel_consumes_allowance=cancel,
    )


def _record(**changes) -> SpotOrderTruthGoalRecord:
    record = SpotOrderTruthGoalRecord(
        goal_id=SPOT_ORDER_TRUTH_GOAL_ID,
        revision=0,
        cycles_used=0,
        active_cycle_number=None,
        last_action=None,
        last_target_client_order_id=None,
        last_outcome="NOT_RUN",
        diagnostic_code="operator_spot_order_truth_not_refreshed",
        category_attempts={
            "api_key_permissions": 0,
            "portfolio_catalog": 0,
            "spot_order_catalog": 0,
        },
        page_count=0,
        order_count=0,
        portfolio_id_sha256=None,
        evidence_sha256=None,
        cancel_outcome="NOT_RUN",
        cancel_exchange_invoked=None,
        cancel_target_client_order_id=None,
        cancel_exchange_order_id_sha256=None,
        correlation_id=None,
        audit_id=None,
        refreshed_at=None,
        updated_at=None,
    )
    return replace(record, **changes)


def _result() -> SpotOrderCatalogResult:
    observation = SpotOrderObservation(
        client_order_id="11111111-1111-4111-8111-111111111111",
        product_id="BTC-USDC",
        side="BUY",
        status="OPEN",
        order_type="LIMIT",
        time_in_force="GOOD_UNTIL_CANCELLED",
        size="0.001",
        limit_price="100",
        filled_size="0",
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:01Z",
        ownership_provenance="ADMIN_MANUAL_ROOT",
        exchange_order_id_sha256="a" * 64,
        authoritatively_nonterminal=True,
        cancel_eligible=True,
    )
    return SpotOrderCatalogResult(
        outcome="SUCCEEDED",
        diagnostic_code="operator_spot_order_truth_catalog_refreshed",
        category_attempts={
            "api_key_permissions": 1,
            "portfolio_catalog": 1,
            "spot_order_catalog": 1,
        },
        page_count=1,
        orders=(observation,),
        credential_can_trade=True,
        portfolio_id_sha256="b" * 64,
        evidence_sha256="c" * 64,
        public_evidence={},
    )


class _Repository:
    def __init__(self) -> None:
        self.record = _record()
        self.cancel_invoked = 0
        self.cancel_finished = []

    def read_goal(self):
        return self.record

    def get_order(self, client_order_id):
        return {
            "client_order_id": client_order_id,
            "product_id": "BTC-USDC",
            "created_at": "2026-01-01T00:00:00Z",
            "ownership_provenance": "ADMIN_MANUAL_ROOT",
            "exchange_order_id_sha256": "a" * 64,
            "authoritatively_nonterminal": True,
            "cancel_eligible": True,
        }

    def begin_cycle(self, *, context, action, target_client_order_id):
        self.record = replace(
            self.record,
            revision=1,
            cycles_used=1,
            active_cycle_number=1,
            last_action=action,
            last_target_client_order_id=target_client_order_id,
            last_outcome="CLAIMED",
        )
        return self.record, 1, False

    def claim_category(self, **_kwargs):
        return None

    def mark_category_invoked(self, **_kwargs):
        return None

    def finish_category(self, **_kwargs):
        return None

    def claim_page(self, **_kwargs):
        return None

    def mark_page_invoked(self, **_kwargs):
        return None

    def finish_page(self, **_kwargs):
        return None

    def fail_page(self, **_kwargs):
        return None

    def finish_cycle(self, *, result, context, action, target_client_order_id, **_):
        self.record = replace(
            self.record,
            revision=2,
            active_cycle_number=None,
            last_outcome=result.outcome,
            diagnostic_code=result.diagnostic_code,
            category_attempts=result.category_attempts,
            page_count=result.page_count,
            order_count=len(result.orders),
            portfolio_id_sha256=result.portfolio_id_sha256,
            evidence_sha256=result.evidence_sha256,
        )
        return self.record

    def claim_cancel(self, **_kwargs):
        self.record = replace(
            self.record,
            revision=3,
            cancel_outcome="CLAIMED",
            cancel_target_client_order_id=_kwargs["client_order_id"],
            cancel_exchange_order_id_sha256=_kwargs[
                "exchange_order_id_sha256"
            ],
        )
        return self.record, "claim-1", False

    def mark_catalog_page_invoked(self, **_kwargs):
        return None

    def mark_cancel_exchange_invoked(self, **_kwargs):
        self.cancel_invoked += 1

    def finish_cancel(self, *, claim_id, execution):
        self.cancel_finished.append((claim_id, execution))
        self.record = replace(
            self.record,
            revision=4,
            cancel_outcome=execution.outcome,
            cancel_exchange_invoked=execution.call_boundary_entered,
        )
        return self.record

    def release_cancel_before_exchange(self, *, claim_id):
        assert claim_id == "claim-1"
        self.record = replace(
            self.record,
            revision=self.record.revision + 1,
            cancel_outcome="NOT_RUN",
            cancel_exchange_invoked=None,
        )
        return self.record


class _Reader:
    def run(self, **kwargs):
        for category in ("api_key_permissions", "portfolio_catalog"):
            kwargs["before_category"](category)
            kwargs["on_category_call_boundary"](category)
            kwargs["after_category"](category, "RETURNED")
        kwargs["before_category"]("spot_order_catalog")
        kwargs["before_page"](1, None)
        kwargs["on_page_call_boundary"](1)
        kwargs["after_page"](1)
        kwargs["after_category"]("spot_order_catalog", "RETURNED")
        return _result()


def test_refresh_uses_one_goal_cycle() -> None:
    repository = _Repository()

    service = OperatorSpotOrderTruthService(
        repository=repository,
        catalog_reader=_Reader(),
    )

    result = service.refresh_catalog(context=_context())

    assert result.cycles_used == 1
    assert result.last_outcome == "SUCCEEDED"
    assert result.cancel_outcome == "NOT_RUN"


def test_public_contract_is_test_profile_spot_only_without_futures_residue() -> None:
    fields = OperatorSpotOrderTruthReadback.model_fields
    assert fields["type"].default == "operator_spot_order_truth"
    assert fields["portfolio_profile_alias"].default == "Test"
    assert fields["product_type"].default == "SPOT"
    properties = OperatorSpotOrderTruthReadback.model_json_schema()[
        "properties"
    ]
    assert properties["cycles_used"]["maximum"] == 1
    assert properties["cycles_remaining"]["maximum"] == 1

    model_source = Path(
        "application/admin_api/operator_spot_order_truth_models.py"
    ).read_text(encoding="utf-8")
    assert "operator_futures" not in model_source
    assert 'Literal["Default"]' not in model_source
    assert "operator_operator" not in model_source
    assert (
        "operator_spot_order_truth_and_exact_cancel_reconcile_v1"
        in model_source
    )


def test_goal12_has_no_parallel_live_cancel_service_path() -> None:
    service_source = Path(
        "application/admin_api/operator_spot_order_truth_service.py"
    ).read_text(encoding="utf-8")
    runtime_source = Path(
        "application/admin_api/operator_spot_order_truth_runtime.py"
    ).read_text(encoding="utf-8")

    assert "def cancel_exact(" not in service_source
    assert "allow_live_execution=True" not in runtime_source
    assert "cancel_order_by_client_order_id(" not in runtime_source


def test_external_coinbase_order_is_omitted_and_never_upgraded_to_manual_root() -> None:
    class RestClient:
        def get_api_key_permissions(self, *, before_sdk_call):
            before_sdk_call()
            return {
                "portfolio_uuid": "approved-test-id",
                "portfolio_type": "CONSUMER",
                "can_view": True,
                "can_trade": True,
            }

        def list_portfolios(self, *, before_sdk_call):
            before_sdk_call()
            return [
                {"uuid": "approved-test-id", "name": "Test"}
            ]

        def list_orders(self, **kwargs):
            kwargs["before_sdk_call"]()
            return {
                "orders": [
                    {
                        "client_order_id": (
                            "22222222-2222-4222-8222-222222222222"
                        ),
                        "order_id": "external-exchange-order",
                        "product_id": "BTC-USDC",
                        "side": "BUY",
                        "status": "OPEN",
                        "order_type": "LIMIT",
                        "time_in_force": "GOOD_UNTIL_CANCELLED",
                        "filled_size": "0",
                        "created_time": "2026-01-01T00:00:00Z",
                        "last_update_time": "2026-01-01T00:00:01Z",
                    }
                ],
                "has_next": False,
            }

    reader = SpotOrderCatalogReader(
        rest_client=RestClient(),
        expected_portfolio_id="approved-test-id",
        local_order_loader=lambda _client_order_id: {
            "client_order_id": "22222222-2222-4222-8222-222222222222",
            "product_id": "BTC-USDC",
            "retail_portfolio_id": "approved-test-id",
            "ownership_provenance": "EXTERNAL_WS_OBSERVED",
            "parent_order_id": None,
        },
    )
    categories = []
    result = reader.run(
        before_category=categories.append,
        on_category_call_boundary=lambda _category: None,
        before_page=lambda _ordinal, _cursor: None,
        on_page_call_boundary=lambda _ordinal: None,
        after_page=lambda _ordinal: None,
    )

    assert result.outcome == "SUCCEEDED"
    assert result.orders == ()
    assert categories == [
        "api_key_permissions",
        "portfolio_catalog",
        "spot_order_catalog",
    ]


def test_catalog_separates_category_claim_from_actual_sdk_boundary() -> None:
    class RestClient:
        def get_api_key_permissions(self, *, before_sdk_call):
            assert callable(before_sdk_call)
            raise ValueError("synthetic_preboundary_failure")

        def list_portfolios(self, *, before_sdk_call):
            raise AssertionError("second category must not run")

        def list_orders(self, **_kwargs):
            raise AssertionError("order catalog must not run")

    claimed: list[str] = []
    invoked: list[str] = []
    reader = SpotOrderCatalogReader(
        rest_client=RestClient(),
        expected_portfolio_id="approved-test-id",
        local_order_loader=lambda _client_order_id: None,
    )

    result = reader.run(
        before_category=claimed.append,
        on_category_call_boundary=invoked.append,
        before_page=lambda _ordinal, _cursor: None,
        on_page_call_boundary=lambda _ordinal: None,
    )

    assert result.outcome == "UNKNOWN"
    assert claimed == ["api_key_permissions"]
    assert invoked == []
    assert result.category_attempts == {
        "api_key_permissions": 0,
        "portfolio_catalog": 0,
        "spot_order_catalog": 0,
    }
    assert result.page_count == 0


def test_catalog_page_preboundary_failure_is_not_counted_as_coinbase_read() -> None:
    class RestClient:
        def get_api_key_permissions(self, *, before_sdk_call):
            before_sdk_call()
            return {
                "portfolio_uuid": "approved-test-id",
                "portfolio_type": "CONSUMER",
                "can_view": True,
                "can_trade": True,
            }

        def list_portfolios(self, *, before_sdk_call):
            before_sdk_call()
            return [{"uuid": "approved-test-id", "name": "Test"}]

        def list_orders(self, **kwargs):
            assert callable(kwargs["before_sdk_call"])
            raise ValueError("synthetic_catalog_preboundary_failure")

    claimed_categories: list[str] = []
    invoked_categories: list[str] = []
    claimed_pages: list[int] = []
    invoked_pages: list[int] = []
    reader = SpotOrderCatalogReader(
        rest_client=RestClient(),
        expected_portfolio_id="approved-test-id",
        local_order_loader=lambda _client_order_id: None,
    )

    result = reader.run(
        before_category=claimed_categories.append,
        on_category_call_boundary=invoked_categories.append,
        before_page=lambda ordinal, _cursor: claimed_pages.append(ordinal),
        on_page_call_boundary=invoked_pages.append,
    )

    assert result.outcome == "UNKNOWN"
    assert claimed_categories == [
        "api_key_permissions",
        "portfolio_catalog",
        "spot_order_catalog",
    ]
    assert invoked_categories == [
        "api_key_permissions",
        "portfolio_catalog",
    ]
    assert claimed_pages == [1]
    assert invoked_pages == []
    assert result.category_attempts == {
        "api_key_permissions": 1,
        "portfolio_catalog": 1,
        "spot_order_catalog": 0,
    }
    assert result.page_count == 0


@pytest.mark.parametrize(
    "client_order_id",
    [
        "11111111-1111-4111-8111-11111111111A",
        "not-a-canonical-uuid",
        "111111111111-1111-8111-111111111111",
    ],
)
def test_catalog_rejects_noncanonical_client_order_id(
    client_order_id: str,
) -> None:
    class RestClient:
        def get_api_key_permissions(self, *, before_sdk_call):
            before_sdk_call()
            return {
                "portfolio_uuid": "approved-test-id",
                "portfolio_type": "CONSUMER",
                "can_view": True,
                "can_trade": True,
            }

        def list_portfolios(self, *, before_sdk_call):
            before_sdk_call()
            return [{"uuid": "approved-test-id", "name": "Test"}]

        def list_orders(self, **kwargs):
            kwargs["before_sdk_call"]()
            return {
                "orders": [
                    {
                        "client_order_id": client_order_id,
                        "order_id": "exchange-order",
                        "product_id": "BTC-USDC",
                        "side": "BUY",
                        "status": "OPEN",
                        "order_type": "LIMIT",
                        "time_in_force": "GOOD_UNTIL_CANCELLED",
                    }
                ],
                "has_next": False,
            }

    reader = SpotOrderCatalogReader(
        rest_client=RestClient(),
        expected_portfolio_id="approved-test-id",
        local_order_loader=lambda _client_order_id: None,
    )
    result = reader.run(
        before_category=lambda _category: None,
        on_category_call_boundary=lambda _category: None,
        before_page=lambda _ordinal, _cursor: None,
        on_page_call_boundary=lambda _ordinal: None,
    )

    assert result.outcome == "UNKNOWN"
    assert result.orders == ()
    assert (
        result.diagnostic_code
        == "operator_spot_order_truth_spot_order_catalog_client_identity_invalid"
    )


@pytest.mark.parametrize(
    "raw_order_type",
    [None, "UNKNOWN_ORDER_TYPE", "NEW_UNDOCUMENTED_ORDER_TYPE"],
)
def test_open_order_with_unknown_type_is_never_cancel_eligible(
    raw_order_type: str | None,
) -> None:
    raw = {
        "client_order_id": "11111111-1111-4111-8111-111111111111",
        "order_id": "private-exchange-order",
        "product_id": "BTC-USDC",
        "side": "BUY",
        "status": "OPEN",
        "time_in_force": "GOOD_UNTIL_CANCELLED",
    }
    if raw_order_type is not None:
        raw["order_type"] = raw_order_type

    observation = _normalize_order(raw)

    assert observation.order_type == "UNKNOWN_ORDER_TYPE"
    assert observation.authoritatively_nonterminal is True
    assert observation.cancel_eligible is False


def test_goal12_sources_are_test_consumer_spot_without_futures_residue() -> None:
    source_paths = (
        Path("application/admin_api/operator_spot_order_truth.py"),
        Path("application/admin_api/operator_spot_order_truth_models.py"),
        Path("application/admin_api/operator_spot_order_truth_runtime.py"),
        Path("application/admin_api/operator_spot_order_truth_service.py"),
        Path(
            "application/admin_api/"
            "operator_spot_order_truth_service_runtime.py"
        ),
        Path("database/operator_spot_order_truth.py"),
    )
    combined = "\n".join(
        path.read_text(encoding="utf-8") for path in source_paths
    )

    assert '"profile_alias": "Test"' in combined
    assert '"portfolio_type": "CONSUMER"' in combined
    assert '"product_type": "SPOT"' in combined
    assert "operator_futures" not in combined
    assert "Default-profile" not in combined
    assert "limited_to_ten" not in combined


def test_manual_root_projection_requires_exact_local_exchange_hash() -> None:
    class RestClient:
        def get_api_key_permissions(self, *, before_sdk_call):
            before_sdk_call()
            return {
                "portfolio_uuid": "approved-test-id",
                "portfolio_type": "CONSUMER",
                "can_view": True,
                "can_trade": True,
            }

        def list_portfolios(self, *, before_sdk_call):
            before_sdk_call()
            return [{"uuid": "approved-test-id", "name": "Test"}]

        def list_orders(self, **kwargs):
            kwargs["before_sdk_call"]()
            return {
                "orders": [
                    {
                        "client_order_id": (
                            "22222222-2222-4222-8222-222222222222"
                        ),
                        "order_id": "coinbase-exchange-id",
                        "product_id": "BTC-USDC",
                        "side": "BUY",
                        "status": "OPEN",
                        "order_type": "LIMIT",
                        "time_in_force": "GOOD_UNTIL_CANCELLED",
                    }
                ],
                "has_next": False,
            }

    local = {
        "client_order_id": "22222222-2222-4222-8222-222222222222",
        "product_id": "BTC-USDC",
        "retail_portfolio_id": "approved-test-id",
        "ownership_provenance": "ADMIN_MANUAL_ROOT",
        "parent_order_id": None,
        "exchange_order_id": "different-exchange-id",
    }
    reader = SpotOrderCatalogReader(
        rest_client=RestClient(),
        expected_portfolio_id="approved-test-id",
        local_order_loader=lambda _client_order_id: local,
    )
    mismatch = reader.run(
        before_category=lambda _category: None,
        on_category_call_boundary=lambda _category: None,
        before_page=lambda _ordinal, _cursor: None,
        on_page_call_boundary=lambda _ordinal: None,
    )
    local["exchange_order_id"] = "coinbase-exchange-id"
    match = reader.run(
        before_category=lambda _category: None,
        on_category_call_boundary=lambda _category: None,
        before_page=lambda _ordinal, _cursor: None,
        on_page_call_boundary=lambda _ordinal: None,
    )

    assert mismatch.orders == ()
    assert len(match.orders) == 1
    assert match.orders[0].ownership_provenance == "ADMIN_MANUAL_ROOT"


def test_exact_reconciliation_returns_only_the_selected_identity() -> None:
    target = "11111111-1111-4111-8111-111111111111"
    unrelated = "22222222-2222-4222-8222-222222222222"

    class RestClient:
        def get_api_key_permissions(self, *, before_sdk_call):
            before_sdk_call()
            return {
                "portfolio_uuid": "approved-test-id",
                "portfolio_type": "CONSUMER",
                "can_view": True,
                "can_trade": True,
            }

        def list_portfolios(self, *, before_sdk_call):
            before_sdk_call()
            return [{"uuid": "approved-test-id", "name": "Test"}]

        def list_orders(self, **kwargs):
            kwargs["before_sdk_call"]()
            return {
                "orders": [
                    {
                        "client_order_id": client_order_id,
                        "order_id": f"exchange-{client_order_id}",
                        "product_id": "BTC-USDC",
                        "side": "BUY",
                        "status": "OPEN",
                        "order_type": "LIMIT",
                        "time_in_force": "GOOD_UNTIL_CANCELLED",
                        "created_time": "2026-01-01T00:00:00Z",
                    }
                    for client_order_id in (target, unrelated)
                ],
                "has_next": False,
            }

    def local_order(client_order_id: str):
        return {
            "client_order_id": client_order_id,
            "product_id": "BTC-USDC",
            "retail_portfolio_id": "approved-test-id",
            "ownership_provenance": "ADMIN_MANUAL_ROOT",
            "parent_order_id": None,
            "exchange_order_id": f"exchange-{client_order_id}",
        }

    result = SpotOrderCatalogReader(
        rest_client=RestClient(),
        expected_portfolio_id="approved-test-id",
        local_order_loader=local_order,
    ).run(
        before_category=lambda _category: None,
        on_category_call_boundary=lambda _category: None,
        before_page=lambda _ordinal, _cursor: None,
        on_page_call_boundary=lambda _ordinal: None,
        exact_scope_required=True,
        target_client_order_id=target,
        target_product_id="BTC-USDC",
        target_created_at="2026-01-01T00:00:00Z",
    )

    assert result.outcome == "SUCCEEDED"
    assert [order.client_order_id for order in result.orders] == [target]


def test_first_exact_reconciliation_scopes_from_canonical_local_root() -> None:
    class Repository(_Repository):
        def get_order(self, _client_order_id):
            return None

    class Reader(_Reader):
        def __init__(self):
            self.kwargs = None

        def run(self, **kwargs):
            self.kwargs = kwargs
            return super().run(**kwargs)

    reader = Reader()
    service = OperatorSpotOrderTruthService(
        repository=Repository(),
        catalog_reader=reader,
        local_order_loader=lambda _client_order_id: {
            "client_order_id": (
                "11111111-1111-4111-8111-111111111111"
            ),
            "product_id": "BTC-USDC",
            "created_at": datetime(2026, 1, 1, 0, 0, 0),
        },
    )
    service.reconcile_exact(
        context=replace(
            _context(),
            operator_intent="reconcile_exact_spot_order",
        ),
        client_order_id="11111111-1111-4111-8111-111111111111",
    )

    assert reader.kwargs["exact_scope_required"] is True
    assert reader.kwargs["target_product_id"] == "BTC-USDC"
    assert reader.kwargs["target_created_at"] == "2026-01-01T00:00:00Z"


def test_first_exact_reconciliation_rejects_ambiguous_local_timestamp_before_reads(
) -> None:
    class Repository(_Repository):
        def get_order(self, _client_order_id):
            return None

    class RestClient:
        def __getattr__(self, _name):
            raise AssertionError(
                "ambiguous local timestamp must fail before Coinbase"
            )

    service = OperatorSpotOrderTruthService(
        repository=Repository(),
        catalog_reader=SpotOrderCatalogReader(
            rest_client=RestClient(),
            expected_portfolio_id="approved-test-id",
            local_order_loader=lambda _client_order_id: None,
        ),
        local_order_loader=lambda _client_order_id: {
            "client_order_id": (
                "11111111-1111-4111-8111-111111111111"
            ),
            "product_id": "BTC-USDC",
            "created_at": "2026-01-01T00:00:00",
        },
    )

    terminal = service.reconcile_exact(
        context=replace(
            _context(),
            operator_intent="reconcile_exact_spot_order",
        ),
        client_order_id="11111111-1111-4111-8111-111111111111",
    )

    assert terminal.last_outcome == "INELIGIBLE"
    assert terminal.diagnostic_code == (
        "operator_spot_order_truth_exact_catalog_scope_incomplete"
    )
