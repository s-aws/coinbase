from datetime import datetime, timezone
from decimal import Decimal

import pytest

from business.spot_direct_order_audit import (
    build_spot_direct_order_audit,
    fetch_direct_order_event_rows,
    fetch_direct_order_fill_rows,
)
from core.enums import (
    EventSourceChannel,
    EventStreamType,
    SpotAuditRecordType,
    SpotDirectOrderAuditStatus,
)
from tools.run_spot_direct_order_audit import SUMMARY_PREFIX, build_parser


pytestmark = pytest.mark.regression


class _FakeDB:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def execute_query(self, query, params):
        self.calls.append((query, params))
        return self.rows


def test_build_spot_direct_order_audit_reports_submission_and_fills():
    report = build_spot_direct_order_audit(
        client_order_id="direct-coid-1",
        generated_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        event_rows=[
            {
                "event_id": "event-1",
                "event_type": EventStreamType.ORDER_SUBMITTED.value,
                "source_channel": EventSourceChannel.REST_SUBMIT.value,
                "client_order_id": "direct-coid-1",
                "order_id": "exchange-1",
                "product_id": "AAA-USDC",
                "side": "BUY",
                "event_status_to": "PENDING",
                "raw_payload_json": {
                    "order_configuration_type": "market_market_ioc",
                    "quote_size": "5",
                },
            },
            {
                "event_id": "event-2",
                "event_type": "order_filled",
                "source_channel": EventSourceChannel.WS_USER.value,
                "client_order_id": "direct-coid-1",
                "order_id": "exchange-1",
            },
        ],
        fill_rows=[
            {
                "id": 1,
                "derived_trade_key": "fill-key-1",
                "instrument": "AAA-USDC",
                "side": "BUY",
                "quantity": Decimal("2"),
                "price": Decimal("2.5"),
                "fees": Decimal("0.01"),
                "reconciliation_status": "RECONCILED",
            }
        ],
    )

    assert report["record_type"] == SpotAuditRecordType.DIRECT_ORDER_AUDIT.value
    assert report["status"] == SpotDirectOrderAuditStatus.FOUND.value
    assert report["client_order_id"] == "direct-coid-1"
    assert report["submission"]["exchange_order_id"] == "exchange-1"
    assert report["submission"]["order_configuration_type"] == "market_market_ioc"
    assert report["submission"]["quote_size"] == "5"
    assert report["event_count"] == 2
    assert report["submission_event_count"] == 1
    assert report["fill_count"] == 1
    assert report["fill_notional"] == "5"
    assert report["fill_fees"] == "0.01"
    assert report["live_coinbase_orders_ran"] is False
    assert report["live_coinbase_requests"] == []


def test_build_spot_direct_order_audit_marks_missing_submission():
    report = build_spot_direct_order_audit(
        client_order_id="direct-coid-2",
        event_rows=[
            {
                "event_type": "order_filled",
                "source_channel": EventSourceChannel.WS_USER.value,
                "client_order_id": "direct-coid-2",
            }
        ],
        fill_rows=[],
        include_events=False,
        include_fills=False,
    )

    assert report["status"] == SpotDirectOrderAuditStatus.MISSING_SUBMISSION.value
    assert report["submission"] is None
    assert "events" not in report
    assert "fills" not in report


def test_fetch_direct_order_audit_rows_are_client_order_id_scoped():
    event_db = _FakeDB([{"event_id": "event-1"}])
    fill_db = _FakeDB([{"derived_trade_key": "fill-1"}])

    assert fetch_direct_order_event_rows(
        db_client=event_db,
        client_order_id="direct-coid-1",
        limit=10,
    ) == [{"event_id": "event-1"}]
    assert fetch_direct_order_fill_rows(
        db_client=fill_db,
        client_order_id="direct-coid-1",
        limit=20,
    ) == [{"derived_trade_key": "fill-1"}]

    event_query, event_params = event_db.calls[0]
    fill_query, fill_params = fill_db.calls[0]
    assert "FROM order_event_stream" in event_query
    assert "WHERE client_order_id = %s" in event_query
    assert event_params == ("direct-coid-1", 10)
    assert "FROM fill_ledger" in fill_query
    assert "WHERE client_order_id = %s" in fill_query
    assert fill_params == ("direct-coid-1", 20)


def test_spot_direct_order_audit_cli_defaults_are_read_only():
    parser = build_parser()
    args = parser.parse_args(["--client-order-id", "direct-coid-1"])

    assert SUMMARY_PREFIX == "SPOT_DIRECT_ORDER_AUDIT "
    assert args.client_order_id == "direct-coid-1"
    assert args.allow_missing is False
    assert args.summary_only is False
