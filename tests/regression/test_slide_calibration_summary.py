"""Regression: slide-calibration summary aggregates and goal math.

Pins the public contract of
``database.slide_calibration_helpers.get_slide_calibration_summary`` —
the data layer behind the ``request_slide_calibration_summary``
WebSocket handler in ``dashboard_server.py``.

These tests stub ``PostgresDB`` so the helper's SQL is never executed;
the focus is the post-aggregation logic (rollups, progress %, capital
turnover, merge of stealth-only products) which is what would silently
drift if someone "tweaks" the helper later.
"""

from __future__ import annotations

from decimal import Decimal
from datetime import datetime, timedelta
from typing import Any, List

import pytest


# ----- Fake DB ----------------------------------------------------------------

class _FakeDB:
    """Minimal stand-in for ``PostgresDB`` returning queued canned rows.

    The helper issues two queries per call (fills + reprices) plus, when
    a stealth-only product exists, a third stealth-counts query. We dispatch
    purely by substring match on the SQL text — fragile in general, but the
    helper's queries are stable and identifiable.
    """

    def __init__(self, fill_rows: List[dict], stealth_count_rows: List[dict],
                 reprice_rows: List[dict]):
        self._fill_rows = fill_rows
        self._stealth_count_rows = stealth_count_rows
        self._reprice_rows = reprice_rows
        self.queries: List[str] = []

    def execute_query(self, sql: str, params=None):
        self.queries.append(sql)
        if "FROM fill_ledger" in sql:
            return self._fill_rows
        if "jsonb_array_elements" in sql:
            return self._reprice_rows
        if "FROM stealth_orders" in sql:
            return self._stealth_count_rows
        raise AssertionError(f"Unexpected query: {sql[:80]}")

    def disconnect(self):
        pass


@pytest.fixture
def patch_db(monkeypatch):
    """Return a function that installs a _FakeDB in the helpers module."""

    def _install(fill_rows=None, stealth_count_rows=None, reprice_rows=None):
        from database import slide_calibration_helpers as mod
        fake = _FakeDB(
            fill_rows or [],
            stealth_count_rows or [],
            reprice_rows or [],
        )
        monkeypatch.setattr(mod, "PostgresDB", lambda: fake)
        return fake

    return _install


# ----- Tests ------------------------------------------------------------------

def _ts(minutes_ago: int) -> datetime:
    return datetime.utcnow() - timedelta(minutes=minutes_ago)


def test_summary_rolls_up_totals_across_products(patch_db):
    """Per-product rows aggregate correctly into the totals block."""
    fill_rows = [
        {
            "product_id": "BTC-USDC",
            "fills_count": 4, "distinct_orders_filled": 2,
            "buy_count": 2, "sell_count": 2,
            "raw_notional": Decimal("400000"),
            "raw_buy_notional": Decimal("180000"),
            "raw_sell_notional": Decimal("220000"),
            "total_quantity": Decimal("5.5"),
            "total_fees": Decimal("12.50"),
            "avg_price": Decimal("75000.00"),
            "min_price": Decimal("74500.00"),
            "max_price": Decimal("75500.00"),
            "price_stdev": Decimal("150.00"),
            "first_fill_at": _ts(120), "last_fill_at": _ts(1),
        },
        {
            "product_id": "ETH-USDC",
            "fills_count": 1, "distinct_orders_filled": 1,
            "buy_count": 0, "sell_count": 1,
            "raw_notional": Decimal("100000"),
            "raw_buy_notional": Decimal("0"),
            "raw_sell_notional": Decimal("100000"),
            "total_quantity": Decimal("30"),
            "total_fees": Decimal("3.00"),
            "avg_price": Decimal("3333.33"),
            "min_price": Decimal("3333.33"),
            "max_price": Decimal("3333.33"),
            "price_stdev": None,
            "first_fill_at": _ts(60), "last_fill_at": _ts(60),
        },
    ]
    stealth_counts = [
        {"product_id": "BTC-USDC",
         "active_orders": 3, "revealed_orders": 1, "unrevealed_orders": 2},
    ]
    reprice_rows = [{"product_id": "BTC-USDC", "reprices_in_window": 9}]

    patch_db(fill_rows, stealth_counts, reprice_rows)

    from database.slide_calibration_helpers import get_slide_calibration_summary
    summary = get_slide_calibration_summary(window_minutes=1440)

    assert summary["window_minutes"] == 1440
    products = {p["product_id"]: p for p in summary["products"]}
    assert set(products) == {"BTC-USDC", "ETH-USDC"}
    btc = products["BTC-USDC"]
    assert btc["fills_count"] == 4
    # No contract sizes supplied → defaults to 1.0, raw notional preserved.
    assert btc["contract_size"] == 1.0
    assert btc["total_notional_usd"] == 400000.0
    assert btc["active_stealth_orders"] == 3
    assert btc["reprices_in_window"] == 9
    assert btc["avg_reprices_per_fill"] == pytest.approx(9 / 4)
    # bps: 150 / 75000 * 10_000 = 20.0
    assert btc["price_stdev_bps"] == pytest.approx(20.0)

    eth = products["ETH-USDC"]
    assert eth["price_stdev_bps"] == 0.0  # NULL stdev → 0

    totals = summary["totals"]
    assert totals["fills_count"] == 5
    assert totals["total_notional_usd"] == 500000.0
    assert totals["sell_notional_usd"] == 320000.0
    assert totals["buy_notional_usd"] == 180000.0
    assert totals["active_stealth_orders"] == 3
    assert totals["reprices_in_window"] == 9


def test_progress_and_turnover_math(patch_db):
    """Targets block computes pct progress and capital turnover correctly."""
    fill_rows = [{
        "product_id": "BTC-USDC",
        "fills_count": 1, "distinct_orders_filled": 1,
        "buy_count": 0, "sell_count": 1,
        "raw_notional": Decimal("500000"),
        "raw_buy_notional": Decimal("0"),
        "raw_sell_notional": Decimal("500000"),
        "total_quantity": Decimal("6.6"),
        "total_fees": Decimal("0"),
        "avg_price": Decimal("75757.57"),
        "min_price": Decimal("75757.57"),
        "max_price": Decimal("75757.57"),
        "price_stdev": None,
        "first_fill_at": _ts(60), "last_fill_at": _ts(60),
    }]
    patch_db(fill_rows, [], [])

    from database.slide_calibration_helpers import get_slide_calibration_summary
    summary = get_slide_calibration_summary(
        window_minutes=1440,
        daily_notional_target_usd=1_000_000.0,
        account_balance_usd=250_000.0,
    )
    t = summary["targets"]
    assert t["notional_progress_pct"] == 50.0       # 500k / 1M
    assert t["capital_turnover"] == pytest.approx(2.0)  # 500k / 250k
    # Window-prorated target: 1440-min window == full daily target.
    assert t["window_notional_target_usd"] == pytest.approx(1_000_000.0)
    assert t["window_notional_progress_pct"] == 50.0


def test_window_target_is_prorated_against_daily(patch_db):
    """A short window must scale the daily target proportionally so the
    "window % to goal" gauge reads like-for-like. Without proration a
    60-minute pull of $500k would read 50% (against daily $1M) when the
    correct read is "you've done 12x your hour's slice of daily target".
    """
    fill_rows = [{
        "product_id": "BTC-USDC",
        "fills_count": 1, "distinct_orders_filled": 1,
        "buy_count": 0, "sell_count": 1,
        "raw_notional": Decimal("500000"),
        "raw_buy_notional": Decimal("0"),
        "raw_sell_notional": Decimal("500000"),
        "total_quantity": Decimal("6.6"),
        "total_fees": Decimal("0"),
        "avg_price": Decimal("75757.57"),
        "min_price": Decimal("75757.57"),
        "max_price": Decimal("75757.57"),
        "price_stdev": None,
        "first_fill_at": _ts(30), "last_fill_at": _ts(30),
    }]
    patch_db(fill_rows, [], [])

    from database.slide_calibration_helpers import get_slide_calibration_summary
    summary = get_slide_calibration_summary(
        window_minutes=60,
        daily_notional_target_usd=1_000_000.0,
        account_balance_usd=250_000.0,
    )
    t = summary["targets"]
    # 60-min slice of daily $1M target = $1M * 60/1440 = $41,666.67
    assert t["window_notional_target_usd"] == pytest.approx(41_666.67, rel=1e-4)
    # $500k actual / $41,666.67 window goal = 1200%
    assert t["window_notional_progress_pct"] == pytest.approx(1200.0, rel=1e-4)
    # Daily KPI unchanged: $500k / $1M = 50%
    assert t["notional_progress_pct"] == 50.0


def test_window_target_zero_daily_does_not_div_zero(patch_db):
    """Defensive: daily_notional_target_usd=0 returns window pct=0, no crash."""
    patch_db()
    from database.slide_calibration_helpers import get_slide_calibration_summary
    summary = get_slide_calibration_summary(
        window_minutes=60, daily_notional_target_usd=0.0
    )
    assert summary["targets"]["window_notional_target_usd"] == 0.0
    assert summary["targets"]["window_notional_progress_pct"] == 0.0
    assert summary["targets"]["notional_progress_pct"] == 0.0


def test_contract_size_scales_futures_notional(patch_db):
    """``BIT-29MAY26-CDE`` 11 contracts at $78,065 → $8,587 notional, not $858,715."""
    fill_rows = [{
        "product_id": "BIT-29MAY26-CDE",
        "fills_count": 1, "distinct_orders_filled": 1,
        "buy_count": 1, "sell_count": 0,
        # raw_notional from SQL = quantity (contracts) * price
        "raw_notional":     Decimal("11") * Decimal("78065"),
        "raw_buy_notional": Decimal("11") * Decimal("78065"),
        "raw_sell_notional": Decimal("0"),
        "total_quantity":   Decimal("11"),
        "total_fees":       Decimal("0"),
        "avg_price":        Decimal("78065"),
        "min_price":        Decimal("78065"),
        "max_price":        Decimal("78065"),
        "price_stdev":      None,
        "first_fill_at":    _ts(5), "last_fill_at": _ts(5),
    }]
    patch_db(fill_rows, [], [])

    from database.slide_calibration_helpers import get_slide_calibration_summary
    summary = get_slide_calibration_summary(
        window_minutes=60,
        contract_size_by_product={"BIT-29MAY26-CDE": 0.01},
    )
    [bit] = summary["products"]
    assert bit["contract_size"] == 0.01
    expected = 11 * 78065 * 0.01
    assert bit["total_notional_usd"] == pytest.approx(expected)
    assert bit["buy_notional_usd"] == pytest.approx(expected)
    # Totals must use scaled values too.
    assert summary["totals"]["total_notional_usd"] == pytest.approx(expected)


def test_unknown_product_defaults_contract_size_to_one(patch_db):
    """Missing entry in lookup → no scaling, never silently invents a multiplier."""
    fill_rows = [{
        "product_id": "MYSTERY-CDE",
        "fills_count": 1, "distinct_orders_filled": 1,
        "buy_count": 1, "sell_count": 0,
        "raw_notional": Decimal("1000"),
        "raw_buy_notional": Decimal("1000"),
        "raw_sell_notional": Decimal("0"),
        "total_quantity": Decimal("1"),
        "total_fees": Decimal("0"),
        "avg_price": Decimal("1000"),
        "min_price": Decimal("1000"),
        "max_price": Decimal("1000"),
        "price_stdev": None,
        "first_fill_at": _ts(1), "last_fill_at": _ts(1),
    }]
    patch_db(fill_rows, [], [])

    from database.slide_calibration_helpers import get_slide_calibration_summary
    summary = get_slide_calibration_summary(
        window_minutes=60,
        contract_size_by_product={"BIT-29MAY26-CDE": 0.01},
    )
    [row] = summary["products"]
    assert row["contract_size"] == 1.0
    assert row["total_notional_usd"] == 1000.0


def test_contract_size_lookup_rejects_invalid_values(patch_db):
    """Zero / negative / non-numeric contract sizes fall back to 1.0."""
    from database.slide_calibration_helpers import _contract_size_for
    bad = {"A": 0, "B": -0.5, "C": "oops", "D": None}
    for pid in bad:
        assert _contract_size_for(pid, bad) == 1.0
    assert _contract_size_for("E", bad) == 1.0  # missing key
    assert _contract_size_for("F", None) == 1.0  # no lookup at all


def test_stealth_only_products_appear_with_zero_fill_row(patch_db):
    """Live orders without fills must still surface in the table."""
    patch_db(
        fill_rows=[],
        stealth_count_rows=[{
            "product_id": "SOL-USDC",
            "active_orders": 2, "revealed_orders": 0, "unrevealed_orders": 2,
        }],
        reprice_rows=[],
    )
    from database.slide_calibration_helpers import get_slide_calibration_summary
    summary = get_slide_calibration_summary(window_minutes=60)
    products = {p["product_id"]: p for p in summary["products"]}
    assert "SOL-USDC" in products
    sol = products["SOL-USDC"]
    assert sol["fills_count"] == 0
    assert sol["total_notional_usd"] == 0.0
    assert sol["active_stealth_orders"] == 2


def test_window_minutes_validated(patch_db):
    """Non-positive windows are rejected before any DB call."""
    patch_db()
    from database.slide_calibration_helpers import get_slide_calibration_summary
    with pytest.raises(ValueError):
        get_slide_calibration_summary(window_minutes=0)
    with pytest.raises(ValueError):
        get_slide_calibration_summary(window_minutes=-5)


def test_active_status_set_excludes_terminal_states():
    """Helper's active-status filter must exclude every terminal state."""
    from database.slide_calibration_helpers import _ACTIVE_STEALTH_STATUSES
    from core.enums import StealthOrderStatus
    assert StealthOrderStatus.ERROR.value not in _ACTIVE_STEALTH_STATUSES
    assert StealthOrderStatus.EXECUTED.value not in _ACTIVE_STEALTH_STATUSES
    assert StealthOrderStatus.CANCELLED.value not in _ACTIVE_STEALTH_STATUSES
    assert StealthOrderStatus.REVEALED.value in _ACTIVE_STEALTH_STATUSES
    assert StealthOrderStatus.HIDDEN.value in _ACTIVE_STEALTH_STATUSES


def test_zero_account_balance_does_not_div_zero(patch_db):
    """Defensive: account_balance_usd=0 returns turnover=0, not crash."""
    patch_db()
    from database.slide_calibration_helpers import get_slide_calibration_summary
    summary = get_slide_calibration_summary(
        window_minutes=60, account_balance_usd=0.0
    )
    assert summary["targets"]["capital_turnover"] == 0.0


def test_reprice_history_sql_accepts_both_object_and_scalar_shapes():
    """Static-source guard: the reprice-counter SQL must match BOTH

      * legacy / current bare-string entries:
            "reprice_history": ["2026-04-29T...", ...]
      * forward object entries:
            "reprice_history": [{"timestamp": "...", ...}, ...]

    The manager currently writes the bare-string form
    (``state.setdefault("reprice_history", []).append(now.isoformat())``);
    a previous reader version only matched objects, which silently
    reported zero reprices in the slide-calibration summary. Pin the
    contract so a future "tidy-up" of the SQL cannot re-introduce that
    blind spot without updating this test.
    """
    import inspect
    from database import slide_calibration_helpers as mod

    src = inspect.getsource(mod._per_product_stealth_metrics)
    assert "jsonb_typeof(evt) = 'object'" in src, (
        "object-shape branch missing from reprice SQL"
    )
    assert "jsonb_typeof(evt) = 'string'" in src, (
        "scalar-string branch missing from reprice SQL — bare ISO "
        "timestamp entries written by stealth_order_manager will be "
        "silently ignored"
    )
    # The scalar branch must use ``#>> '{}'`` to extract the JSONB
    # string as plain text (``->> 'timestamp'`` would not work on a
    # scalar). Pin that detail too.
    assert "evt #>> '{}'" in src
