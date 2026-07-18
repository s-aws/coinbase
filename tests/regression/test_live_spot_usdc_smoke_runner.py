"""Regression checks for the live spot smoke runner helpers."""

from decimal import Decimal
from pathlib import Path
import os

import pytest

from tools.run_live_spot_usdc_smoke import (
    LiveOrderReport,
    _build_summary,
    _build_reconciliation_gate,
    _client_order_id,
    _fills_notional_and_size,
    _submit_limit_sell_cancel_smoke,
)
from core.enums import SpotFillBackfillStatus, SpotLiveReconciliationGateStatus
from tools.run_spot_fill_backfill_recovery import (
    build_recovery_summary,
    collect_backfill_order_reports,
)
from tools import run_live_spot_usdc_smoke as live_smoke


pytestmark = [
    pytest.mark.regression,
    pytest.mark.usefixtures("coinbase_execution_lease"),
]


@pytest.mark.parametrize("configured_value", [None, "", "0", "true", "yes", "01"])
def test_live_spot_smoke_requires_exact_outer_authority_before_sdk_construction(
    monkeypatch: pytest.MonkeyPatch,
    configured_value: str | None,
) -> None:
    if configured_value is None:
        monkeypatch.delenv("COINBASE_EXECUTION_ENABLED", raising=False)
    else:
        monkeypatch.setenv("COINBASE_EXECUTION_ENABLED", configured_value)
    monkeypatch.setenv("COINBASE_API_KEY", "synthetic-key")
    monkeypatch.setenv("COINBASE_API_SECRET", "synthetic-secret")

    def unexpected_sdk(*args, **kwargs):
        raise AssertionError("SDK must not be constructed without exact authority")

    monkeypatch.setattr(live_smoke, "RESTClient", unexpected_sdk)

    with pytest.raises(SystemExit) as exc_info:
        live_smoke.main(
            [
                "--approved-live-orders",
                "--skip-market",
                "--audit-file",
                os.devnull,
            ]
        )

    assert exc_info.value.code == 2


def test_live_spot_smoke_main_is_source_disabled_before_sdk_construction(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    private_marker = "PRIVATE-SMOKE-MAIN-EXCEPTION-MARKER"
    audit_file = tmp_path / "live-smoke.jsonl"
    monkeypatch.setenv("COINBASE_EXECUTION_ENABLED", "1")
    monkeypatch.setenv("COINBASE_API_KEY", "synthetic-key")
    monkeypatch.setenv("COINBASE_API_SECRET", "synthetic-secret")

    def fail_sdk(*_args, **_kwargs):
        raise RuntimeError(private_marker)

    monkeypatch.setattr(live_smoke, "RESTClient", fail_sdk)

    with pytest.raises(SystemExit) as exc_info:
        live_smoke.main(
            [
                "--approved-live-orders",
                "--skip-market",
                "--audit-file",
                str(audit_file),
            ]
        )

    output = capsys.readouterr()
    assert exc_info.value.code == 2
    assert private_marker not in output.out
    assert private_marker not in output.err
    assert (
        "coinbase_execution_surface_source_disabled_use_authenticated_admin_api"
        in output.err
    )
    assert not audit_file.exists()


class FakeClient:
    def __init__(self, fills):
        self.fills = fills

    def get_fills(self, **kwargs):
        assert kwargs["order_ids"] == ["order-1"]
        assert "product_ids" not in kwargs
        return {"fills": self.fills}


def test_live_spot_smoke_fill_parser_handles_quote_sized_buy_fill():
    client = FakeClient([
        {
            "price": "0.00000012",
            "size": "0.9993504",
            "size_in_quote": True,
        },
    ])

    base_size, notional = _fills_notional_and_size(
        client,
        "MOG-USDC",
        "order-1",
    )

    assert base_size == Decimal("8327920")
    assert notional == Decimal("0.9993504")


def test_live_spot_smoke_fill_parser_handles_base_sized_sell_fill():
    client = FakeClient([
        {
            "price": "0.0000001100027",
            "size": "8327920",
            "size_in_quote": False,
        },
    ])

    base_size, notional = _fills_notional_and_size(
        client,
        "MOG-USDC",
        "order-1",
    )

    assert base_size == Decimal("8327920")
    assert notional == Decimal("0.916093685384")


def test_live_spot_smoke_summary_reports_retained_inventory():
    summary = _build_summary(
        product={
            "product_id": "MOG-USDC",
            "quote_min_size": "1",
            "price": "0.00000012",
            "base_increment": "1",
            "quote_increment": "0.00000001",
        },
        quote_size=Decimal("1"),
        preview={"best_bid": "0.00000011", "best_ask": "0.00000012"},
        reports=[
            LiveOrderReport(
                label="market_sell",
                product_id="MOG-USDC",
                order_type="market_ioc",
                side="SELL",
                client_order_id="",
                exchange_order_id=None,
                submitted_notional_usdc="0",
                executed_notional_usdc="0",
                status="skipped_retained_inventory",
                base_size="8327920",
            ),
        ],
    )

    assert summary["retained_base_by_product"] == {"MOG-USDC": "8327920"}


def test_live_spot_reconciliation_gate_requires_market_fill_backfill():
    summary = {
        "orders": [
            {
                "label": "matrix_market_buy",
                "exchange_order_id": "order-buy",
                "executed_notional_usdc": "1",
            },
        ],
        "fill_backfill": {
            "total_fetched_fill_count": 1,
            "total_appended_fill_count": 1,
            "orders": [
                {
                    "exchange_order_id": "order-buy",
                    "fetched_fill_count": 1,
                    "status": SpotFillBackfillStatus.APPENDED.value,
                },
            ],
        },
    }

    gate = _build_reconciliation_gate(summary)

    assert gate["status"] == SpotLiveReconciliationGateStatus.PASSED.value
    assert gate["checked_order_count"] == 1


def test_live_spot_reconciliation_gate_value_blinds_backfill_error_text():
    private_marker = "PRIVATE-RECONCILIATION-ERROR-MARKER"
    summary = {
        "orders": [
            {
                "label": "matrix_market_buy",
                "exchange_order_id": "order-buy",
                "executed_notional_usdc": "1",
            },
        ],
        "fill_backfill": {
            "error": private_marker,
            "orders": [
                {
                    "exchange_order_id": "order-buy",
                    "fetched_fill_count": 0,
                    "status": SpotFillBackfillStatus.ERROR.value,
                    "error": private_marker,
                }
            ],
        },
    }

    gate = _build_reconciliation_gate(summary)

    assert gate["status"] == SpotLiveReconciliationGateStatus.FAILED.value
    assert private_marker not in str(gate)
    assert "fill backfill failed" in gate["failures"]
    assert "fill-ledger backfill errored for order-buy" in gate["failures"]


def test_live_spot_smoke_generated_client_order_ids_fit_fill_ledger_limit():
    assert len(_client_order_id("lmb")) <= 40
    assert len(_client_order_id("lsls")) <= 40


def test_live_spot_smoke_mutations_are_each_preceded_by_authority_recheck(
    monkeypatch: pytest.MonkeyPatch,
):
    events = []

    class FakeMutationClient:
        def limit_order_gtc(self, **kwargs):
            events.append(f"mutate:limit:{kwargs['side']}")
            return {
                "success": True,
                "success_response": {"order_id": f"limit-{kwargs['side']}"},
            }

        def cancel_orders(self, order_ids):
            events.append(f"mutate:cancel:{order_ids[0]}")

        def market_order_buy(self, **_kwargs):
            events.append("mutate:market:BUY")
            return {
                "success": True,
                "success_response": {"order_id": "market-buy"},
            }

        def market_order_sell(self, **_kwargs):
            events.append("mutate:market:SELL")
            return {
                "success": True,
                "success_response": {"order_id": "market-sell"},
            }

    monkeypatch.setattr(
        live_smoke,
        "require_coinbase_execution_authority",
        lambda: events.append("authority"),
    )
    monkeypatch.setattr(
        live_smoke,
        "_poll_order",
        lambda *_args, **_kwargs: {
            "status": "FILLED",
            "average_filled_price": "1",
        },
    )
    monkeypatch.setattr(
        live_smoke,
        "_order_executed_notional",
        lambda *_args, **_kwargs: (Decimal("1"), Decimal("1")),
    )
    client = FakeMutationClient()
    product = {
        "product_id": "MOG-USDC",
        "price": "1",
        "price_increment": "0.01",
        "base_increment": "0.01",
    }
    preview = {"best_bid": "1", "best_ask": "1"}

    live_smoke._submit_limit_cancel_smoke(
        client,
        product,
        Decimal("1"),
        preview,
    )
    live_smoke._submit_limit_sell_cancel_smoke(
        client,
        product,
        Decimal("1"),
        preview,
    )
    live_smoke._submit_market_round_trip_smoke(
        client,
        product,
        Decimal("1"),
    )
    live_smoke._submit_validation_matrix_smoke(
        client,
        product,
        Decimal("1"),
        preview,
    )

    assert events == [
        "authority",
        "mutate:limit:BUY",
        "authority",
        "mutate:cancel:limit-BUY",
        "authority",
        "mutate:limit:SELL",
        "authority",
        "mutate:cancel:limit-SELL",
        "authority",
        "mutate:market:BUY",
        "authority",
        "mutate:market:SELL",
        "authority",
        "mutate:market:BUY",
        "authority",
        "mutate:limit:BUY",
        "authority",
        "mutate:cancel:limit-BUY",
        "authority",
        "mutate:limit:SELL",
        "authority",
        "mutate:cancel:limit-SELL",
        "authority",
        "mutate:market:SELL",
    ]


def test_live_spot_smoke_revocation_blocks_cancel_after_submission(
    monkeypatch: pytest.MonkeyPatch,
):
    events = []
    authority_checks = 0

    def require_current_authority():
        nonlocal authority_checks
        authority_checks += 1
        events.append("authority")
        if authority_checks == 2:
            raise live_smoke.CoinbaseExecutionAuthorityError(
                "coinbase_execution_authority_missing"
            )

    class RevokedClient:
        def limit_order_gtc(self, **_kwargs):
            events.append("mutate:limit")
            return {
                "success": True,
                "success_response": {"order_id": "order-1"},
            }

        def cancel_orders(self, _order_ids):
            events.append("mutate:cancel")

        def get_order(self, _order_id):
            return {"order": {"status": "OPEN"}}

        def get_fills(self, **_kwargs):
            return {"fills": []}

    monkeypatch.setattr(
        live_smoke,
        "require_coinbase_execution_authority",
        require_current_authority,
    )
    monkeypatch.setattr(
        live_smoke,
        "_order_executed_notional",
        lambda *_args, **_kwargs: (Decimal("0"), Decimal("0")),
    )

    report = live_smoke._submit_limit_cancel_smoke(
        RevokedClient(),
        {
            "product_id": "MOG-USDC",
            "price": "1",
            "price_increment": "0.01",
            "base_increment": "0.01",
        },
        Decimal("1"),
        {"best_bid": "1"},
    )

    assert events == ["authority", "mutate:limit", "authority"]
    assert report.status == "error"
    assert report.error == "exception_class:CoinbaseExecutionAuthorityError"


def test_live_spot_smoke_limit_sell_helper_submits_post_only_and_cancels(
    monkeypatch: pytest.MonkeyPatch,
):
    class FakeLimitSellClient:
        def __init__(self):
            self.limit_calls = []
            self.cancel_calls = []

        def limit_order_gtc(self, **kwargs):
            self.limit_calls.append(kwargs)
            return {"success": True, "success_response": {"order_id": "order-1"}}

        def cancel_orders(self, order_ids):
            self.cancel_calls.append(order_ids)

        def get_order(self, order_id):
            assert order_id == "order-1"
            return {"order": {"status": "CANCELLED"}}

        def get_fills(self, **kwargs):
            assert kwargs["order_ids"] == ["order-1"]
            return {"fills": []}

    monkeypatch.setattr(
        live_smoke,
        "require_coinbase_execution_authority",
        lambda: None,
    )
    client = FakeLimitSellClient()

    report = _submit_limit_sell_cancel_smoke(
        client,
        {
            "product_id": "MOG-USDC",
            "price_increment": "0.00000001",
            "base_increment": "1",
        },
        Decimal("8327920"),
        {"best_ask": "0.00000012"},
    )

    assert report.label == "post_only_limit_sell_cancel"
    assert report.side == "SELL"
    assert report.order_type == "limit_gtc_post_only"
    assert report.submitted_notional_usdc == "1.0826296"
    assert client.limit_calls[0]["post_only"] is True
    assert client.cancel_calls == [["order-1"]]


def test_live_spot_smoke_value_blinds_exchange_exception_text(
    monkeypatch: pytest.MonkeyPatch,
):
    private_marker = "PRIVATE-SMOKE-EXCEPTION-MARKER"

    class FailingLimitSellClient:
        def limit_order_gtc(self, **_kwargs):
            raise RuntimeError(private_marker)

    monkeypatch.setattr(
        live_smoke,
        "require_coinbase_execution_authority",
        lambda: None,
    )
    report = _submit_limit_sell_cancel_smoke(
        FailingLimitSellClient(),
        {
            "product_id": "MOG-USDC",
            "price_increment": "0.00000001",
            "base_increment": "1",
        },
        Decimal("8327920"),
        {"best_ask": "0.00000012"},
    )

    assert report.status == "error"
    assert report.error == "exception_class:RuntimeError"
    assert private_marker not in str(report)


def test_live_spot_smoke_fails_closed_on_create_response_without_explicit_success(
    monkeypatch: pytest.MonkeyPatch,
):
    private_marker = "PRIVATE-SMOKE-CREATE-RESPONSE-MARKER"

    class MissingSuccessLimitSellClient:
        def __init__(self):
            self.cancel_calls = []

        def limit_order_gtc(self, **_kwargs):
            return {
                "success_response": {
                    "order_id": "exchange-order-ambiguous",
                    "private_extension": private_marker,
                },
                "private_top_level": private_marker,
            }

        def cancel_orders(self, order_ids):
            self.cancel_calls.append(order_ids)

        def get_order(self, order_id):
            assert order_id == "exchange-order-ambiguous"
            return {"order": {"status": "CANCELLED"}}

        def get_fills(self, **_kwargs):
            return {"fills": []}

    monkeypatch.setattr(
        live_smoke,
        "require_coinbase_execution_authority",
        lambda: None,
    )
    client = MissingSuccessLimitSellClient()
    report = _submit_limit_sell_cancel_smoke(
        client,
        {
            "product_id": "MOG-USDC",
            "price_increment": "0.00000001",
            "base_increment": "1",
        },
        Decimal("8327920"),
        {"best_ask": "0.00000012"},
    )
    summary = _build_summary(
        product={"product_id": "MOG-USDC"},
        quote_size=Decimal("1"),
        preview={},
        reports=[report],
    )

    assert report.response_success is None
    assert report.submission_attempted is True
    assert report.error == "coinbase_create_acceptance_unknown"
    assert private_marker not in str(report)
    assert client.cancel_calls == [["exchange-order-ambiguous"]]
    assert summary["live_coinbase_orders_ran"] is True


def test_live_spot_smoke_value_blinds_preview_and_backfill_exception_text(
    monkeypatch: pytest.MonkeyPatch,
):
    private_marker = "PRIVATE-SMOKE-BACKFILL-MARKER"

    class FailingPreviewClient:
        def preview_market_order_buy(self, **_kwargs):
            raise RuntimeError(private_marker)

    with pytest.raises(RuntimeError) as preview_error:
        live_smoke._first_previewable_product(
            FailingPreviewClient(),
            [
                {
                    "product_id": "MOG-USDC",
                    "quote_increment": "0.01",
                    "quote_min_size": "1",
                }
            ],
            None,
        )
    assert "exception_class:RuntimeError" in str(preview_error.value)
    assert private_marker not in str(preview_error.value)

    import business.fill_ledger as fill_ledger_module
    import business.spot_fill_backfill as backfill_module
    import database.database as database_module

    monkeypatch.setattr(fill_ledger_module, "FillLedgerRepository", lambda _db: object())
    monkeypatch.setattr(database_module, "PostgresDB", lambda: object())

    def fail_backfill(**_kwargs):
        raise RuntimeError(private_marker)

    monkeypatch.setattr(
        backfill_module,
        "backfill_fill_ledger_from_order_reports",
        fail_backfill,
    )
    result = live_smoke._backfill_live_smoke_fills(client=object(), reports=[])

    assert result["error"] == "exception_class:RuntimeError"
    assert private_marker not in str(result)


def test_spot_fill_backfill_recovery_collects_durable_smoke_and_sweep_orders():
    smoke_records = [
        {
            "record_type": "live_spot_usdc_smoke",
            "orders": [
                {
                    "product_id": "MOG-USDC",
                    "side": "BUY",
                    "client_order_id": "coid-smoke",
                    "exchange_order_id": "exchange-smoke",
                    "status": "FILLED",
                },
            ],
        },
    ]
    sweep_records = [
        {
            "record_type": "sweep_run",
            "config_id": "cfg-1",
            "run_id": "run-1",
            "execution": {
                "orders": [
                    {
                        "product_id": "AAA-USDC",
                        "side": "SELL",
                        "client_order_id": "coid-sweep",
                        "exchange_order_id": "exchange-sweep",
                        "status": "submitted",
                    },
                    {
                        "product_id": "AAA-USDC",
                        "side": "SELL",
                        "client_order_id": "coid-sweep",
                        "exchange_order_id": "exchange-sweep",
                        "status": "submitted",
                    },
                ],
            },
        },
    ]

    orders = collect_backfill_order_reports(
        smoke_records=smoke_records,
        sweep_records=sweep_records,
        smoke_audit_file=Path("runtime_state/live_spot_usdc_smoke.jsonl"),
        sweep_state_file=Path("runtime_state/spot_portfolio_sweeps.jsonl"),
        source="all",
    )

    assert len(orders) == 2
    assert {order["source"] for order in orders} == {"smoke", "sweep"}
    assert orders[1]["run_id"] == "run-1"


def test_spot_fill_backfill_recovery_summary_reports_zero_live_notional():
    summary = build_recovery_summary(
        orders=[
            {
                "source": "sweep",
                "source_status": "submitted",
                "client_order_id": "coid-1",
                "exchange_order_id": "exchange-1",
            },
            {
                "source": "sweep",
                "source_status": "skipped",
                "client_order_id": None,
                "exchange_order_id": None,
            },
        ],
        dry_run=True,
        source="sweep",
        smoke_audit_file=Path("runtime_state/live_spot_usdc_smoke.jsonl"),
        sweep_state_file=Path("runtime_state/spot_portfolio_sweeps.jsonl"),
    )

    assert summary["candidate_order_count"] == 2
    assert summary["eligible_order_count"] == 1
    assert summary["live_coinbase_orders_ran"] is False
    assert summary["live_order_notional_usdc"] == "0"
    assert summary["read_only_coinbase_requests"] == []
