"""Unit tests for ``engine_console`` filter and rendering logic.

The interactive layer (prompt_toolkit Application, WS consumer) is not
covered here — it's I/O-bound and best validated by running the tool.
These tests pin the deterministic, pure-function behaviour:
``FilterState`` and the renderer composition for known snapshots.
"""
from __future__ import annotations

from collections import deque

import pytest

from engine_console import (
    FilterState,
    Snapshot,
    LOG_LEVELS,
    render_logs,
    render_positions,
    render_stealth_orders,
)


# ---------------------------------------------------------------------------
# FilterState.log_passes — the contract
# ---------------------------------------------------------------------------


def test_log_passes_default_filters_info_and_above():
    fs = FilterState()
    assert fs.log_passes("INFO", "anything", {}) is True
    assert fs.log_passes("WARNING", "x", {}) is True
    assert fs.log_passes("ERROR", "x", {}) is True
    assert fs.log_passes("DEBUG", "x", {}) is False


def test_log_passes_min_level_strictly_enforced():
    fs = FilterState(min_level="WARNING")
    assert fs.log_passes("INFO", "x", {}) is False
    assert fs.log_passes("WARNING", "x", {}) is True
    assert fs.log_passes("CRITICAL", "x", {}) is True


def test_log_passes_event_excludes_uses_context_event_first():
    fs = FilterState(event_excludes={"heartbeat"})
    assert fs.log_passes("INFO", "heartbeat tick", {"event": "heartbeat"}) is False
    # Without context, falls back to first message token.
    assert fs.log_passes("INFO", "heartbeat tick", {}) is False
    assert fs.log_passes("INFO", "real_event details", {"event": "real_event"}) is True


def test_log_passes_product_filter_substring_in_message_or_context():
    fs = FilterState(product_filter="BIP")
    assert fs.log_passes("INFO", "fill on BIP-20DEC30-CDE", {}) is True
    assert fs.log_passes("INFO", "fill on BTC-USDC", {}) is False
    # Context fallback when message lacks product reference.
    assert fs.log_passes("INFO", "fill", {"product_id": "BIP-20DEC30-CDE"}) is True


def test_log_passes_search_substring_case_insensitive():
    fs = FilterState(search_substring="REPLACEMENT")
    assert fs.log_passes("INFO", "max replacement reached", {}) is True
    assert fs.log_passes("INFO", "max placements reached", {}) is False


def test_filter_reset_restores_defaults():
    fs = FilterState(
        product_filter="BIP",
        min_level="ERROR",
        event_excludes={"x"},
        search_substring="y",
        sort_stealth_by="size",
        show_orders=False,
        paused=True,
    )
    fs.reset()
    assert fs.product_filter is None
    assert fs.min_level == "INFO"
    assert fs.event_excludes == set()
    assert fs.search_substring is None
    assert fs.sort_stealth_by == "created"
    assert fs.show_orders is True
    assert fs.paused is False


def test_log_levels_constant_matches_python_logging_ranking():
    # Sanity: the rank order must put ERROR above WARNING above INFO.
    assert LOG_LEVELS.index("ERROR") > LOG_LEVELS.index("WARNING")
    assert LOG_LEVELS.index("WARNING") > LOG_LEVELS.index("INFO")
    assert LOG_LEVELS.index("INFO") > LOG_LEVELS.index("DEBUG")


# ---------------------------------------------------------------------------
# Renderer composition — sanity that filters are honored in output
# ---------------------------------------------------------------------------


def _ftext_to_str(ftext) -> str:
    return "".join(text for _style, text in ftext)


def test_render_logs_filters_to_visible_subset():
    fs = FilterState(min_level="WARNING")
    buf = deque([
        {"timestamp": "2026-04-30T09:14:00", "level": "INFO", "message": "noise", "context": {}},
        {"timestamp": "2026-04-30T09:14:01", "level": "WARNING", "message": "warn-thing", "context": {}},
        {"timestamp": "2026-04-30T09:14:02", "level": "ERROR", "message": "bad-thing", "context": {}},
    ])
    out = _ftext_to_str(render_logs(buf, fs, width=80, height=10))
    assert "noise" not in out
    assert "warn-thing" in out
    assert "bad-thing" in out
    # Counter shows visible/total.
    assert "[2/3 buffered]" in out


def test_render_logs_product_filter_excludes_other_products():
    fs = FilterState(product_filter="BIP")
    buf = deque([
        {"timestamp": "2026-04-30T09:14:00", "level": "INFO", "message": "fill BTC-USDC", "context": {}},
        {"timestamp": "2026-04-30T09:14:01", "level": "INFO", "message": "fill BIP-20DEC30-CDE", "context": {}},
    ])
    out = _ftext_to_str(render_logs(buf, fs, width=80, height=10))
    assert "BTC-USDC" not in out
    assert "BIP-20DEC30-CDE" in out


def test_render_positions_respects_product_filter():
    fs = FilterState(product_filter="BIP")
    snap = Snapshot(
        positions={
            "BIP-20DEC30-CDE": {"side": "SHORT", "quantity": -417, "avg_price": 75734.37, "unrealized_pnl": 1247.10},
            "BTC-USDC": {"side": "LONG", "quantity": 0.5, "avg_price": 76000, "unrealized_pnl": -10.0},
        }
    )
    out = _ftext_to_str(render_positions(snap, fs, width=120))
    assert "BIP-20DEC30-CDE" in out
    assert "BTC-USDC" not in out


def test_render_positions_hidden_when_show_positions_false():
    fs = FilterState(show_positions=False)
    snap = Snapshot(positions={"BIP-20DEC30-CDE": {"side": "SHORT", "quantity": -1}})
    out = _ftext_to_str(render_positions(snap, fs, width=120))
    assert "BIP-20DEC30-CDE" not in out
    assert "hidden" in out


def test_render_stealth_orders_sort_by_size_descending():
    fs = FilterState(sort_stealth_by="size")
    snap = Snapshot(stealth_orders={
        "small1234567": {"product_id": "BIP", "side": "BUY", "total_size": 1.0, "status": "HIDDEN"},
        "big123456789": {"product_id": "BIP", "side": "SELL", "total_size": 100.0, "status": "HIDDEN"},
    })
    out = _ftext_to_str(render_stealth_orders(snap, fs, width=120))
    big_pos = out.find("big1234")
    small_pos = out.find("small12")
    assert big_pos != -1 and small_pos != -1
    assert big_pos < small_pos, "Larger size must render above smaller when sort=size"
