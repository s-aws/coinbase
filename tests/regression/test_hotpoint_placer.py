"""Tests for ``business.hotpoint_placer``."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from business.hotpoint_detector import HotpointTriggerEvent
from business.hotpoint_placer import (
    STATUS_DB_INSERT_FAILED,
    STATUS_INVALID_PRICE,
    STATUS_KILL_SWITCH_OFF,
    STATUS_PLACED,
    STATUS_PRODUCT_META_MISSING,
    STATUS_RATE_LIMITED,
    STATUS_REST_FAILED,
    derive_placement_price,
    place_hotpoint_order,
)
from business.hotpoint_rate_limiter import HotpointRateLimiter
from core.enums import HotpointPlacementPolicy


pytestmark = pytest.mark.regression


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------

def _make_event(**overrides):
    defaults = dict(
        product_id="BTC-USDC",
        side="BUY",
        bucket_id=42,
        bucket_center=100.0,
        fills_in_window=3,
        last_fill_price=99.7,
        mean_fill_price=100.1,
        triggered_at=0.0,
    )
    defaults.update(overrides)
    return HotpointTriggerEvent(**defaults)


def _good_meta():
    return {"base_min_size": 0.001, "base_increment": 0.001, "price_increment": 0.5}


def _make_call(**overrides):
    rl = overrides.pop("rate_limiter", None) or HotpointRateLimiter(
        cap_n=5, window_seconds=60
    )
    rest = overrides.pop("rest_client", None) or MagicMock()
    insert = overrides.pop("insert_order_parent_fn", None) or MagicMock(return_value=1)
    defaults = dict(
        event=_make_event(),
        rate_limiter=rl,
        product_meta=_good_meta(),
        policy=HotpointPlacementPolicy.WINDOW_CENTER,
        rest_client=rest,
        insert_order_parent_fn=insert,
        kill_switch_enabled=True,
        log_callback=MagicMock(),
        now_epoch=0.0,
    )
    defaults.update(overrides)
    result = place_hotpoint_order(**defaults)
    return result, rl, rest, insert


# ----------------------------------------------------------------------------
# Pricing policy
# ----------------------------------------------------------------------------

def test_derive_price_window_center():
    ev = _make_event(bucket_center=123.456)
    assert derive_placement_price(HotpointPlacementPolicy.WINDOW_CENTER, ev) == 123.456


def test_derive_price_last_fill():
    ev = _make_event(last_fill_price=77.7)
    assert derive_placement_price(HotpointPlacementPolicy.LAST_FILL, ev) == 77.7


def test_derive_price_mean_of_fills():
    ev = _make_event(mean_fill_price=88.8)
    assert derive_placement_price(HotpointPlacementPolicy.MEAN_OF_FILLS, ev) == 88.8


# ----------------------------------------------------------------------------
# Happy path
# ----------------------------------------------------------------------------

def test_happy_path_places_and_persists():
    result, rl, rest, insert = _make_call()
    assert result.status == STATUS_PLACED
    assert result.client_order_id is not None
    assert result.submitted_price == 100.0  # quantized to 0.5 tick
    assert result.submitted_size == 0.001
    rest.limit_order_gtc.assert_called_once()
    insert.assert_called_once()
    # Inserted row carries the marker flags.
    kw = insert.call_args.kwargs
    assert kw["auto_placed_by_hotpoint"] is True
    assert kw["enable_hotpoint_replication"] is False
    assert kw["parent_order_id"] is None
    # Slot was committed (not rolled back).
    assert rl.current_count(product_id="BTC-USDC", side="BUY", bucket_id=42, now=0.0) == 1


def test_quantize_price_to_tick():
    """Bucket center 100.4 should round to nearest 0.5 tick = 100.5."""
    ev = _make_event(bucket_center=100.4)
    result, _, rest, _ = _make_call(event=ev)
    assert result.status == STATUS_PLACED
    assert result.submitted_price == 100.5
    submitted = rest.limit_order_gtc.call_args.kwargs
    assert submitted["limit_price"] == "100.5"


# ----------------------------------------------------------------------------
# Gates
# ----------------------------------------------------------------------------

def test_kill_switch_off_skips_everything():
    result, rl, rest, insert = _make_call(kill_switch_enabled=False)
    assert result.status == STATUS_KILL_SWITCH_OFF
    rest.limit_order_gtc.assert_not_called()
    insert.assert_not_called()
    # Slot was never acquired.
    assert rl.current_count(product_id="BTC-USDC", side="BUY", bucket_id=42, now=0.0) == 0


def test_rate_limit_blocks_placement():
    rl = HotpointRateLimiter(cap_n=1, window_seconds=60)
    rl.try_acquire(product_id="BTC-USDC", side="BUY", bucket_id=42, now=0.0)
    rl.commit(product_id="BTC-USDC", side="BUY", bucket_id=42, now=0.0)
    result, _, rest, insert = _make_call(rate_limiter=rl)
    assert result.status == STATUS_RATE_LIMITED
    rest.limit_order_gtc.assert_not_called()
    insert.assert_not_called()


def test_missing_price_increment_returns_meta_missing_and_releases_slot():
    bad_meta = {"base_min_size": 0.001, "price_increment": 0}
    result, rl, rest, insert = _make_call(product_meta=bad_meta)
    assert result.status == STATUS_PRODUCT_META_MISSING
    rest.limit_order_gtc.assert_not_called()
    insert.assert_not_called()
    assert rl.current_count(product_id="BTC-USDC", side="BUY", bucket_id=42, now=0.0) == 0


def test_missing_base_min_size_returns_meta_missing():
    bad_meta = {"base_min_size": 0, "price_increment": 0.5}
    result, _, _, _ = _make_call(product_meta=bad_meta)
    assert result.status == STATUS_PRODUCT_META_MISSING


def test_negative_derived_price_releases_slot():
    # Bucket center is computed from bucket_id, but a malicious event with
    # bucket_center=-1 simulates a corrupted event; placer must defend.
    ev = _make_event(bucket_center=-1.0)
    result, rl, rest, _ = _make_call(event=ev)
    assert result.status == STATUS_INVALID_PRICE
    rest.limit_order_gtc.assert_not_called()
    assert rl.current_count(product_id="BTC-USDC", side="BUY", bucket_id=42, now=0.0) == 0


# ----------------------------------------------------------------------------
# Failure paths
# ----------------------------------------------------------------------------

def test_rest_failure_releases_slot_and_returns_status():
    rest = MagicMock()
    rest.limit_order_gtc.side_effect = RuntimeError("boom")
    result, rl, _, insert = _make_call(rest_client=rest)
    assert result.status == STATUS_REST_FAILED
    assert "boom" in (result.error or "")
    insert.assert_not_called()
    # Slot was rolled back.
    assert rl.current_count(product_id="BTC-USDC", side="BUY", bucket_id=42, now=0.0) == 0


def test_db_insert_failure_keeps_slot_committed():
    """If REST succeeded but DB insert failed, the order IS on exchange.

    Slot must be committed so we don't blow the cap on the next trigger
    and end up with two real orders against one cap slot.
    """
    insert = MagicMock(side_effect=RuntimeError("db down"))
    rest = MagicMock()
    result, rl, _, _ = _make_call(rest_client=rest, insert_order_parent_fn=insert)
    assert result.status == STATUS_DB_INSERT_FAILED
    rest.limit_order_gtc.assert_called_once()
    # Slot committed (count = 1).
    assert rl.current_count(product_id="BTC-USDC", side="BUY", bucket_id=42, now=0.0) == 1


def test_unexpected_exception_in_meta_read_releases_slot():
    """Coverage for the outer try/except safety net."""

    class Exploding:
        def get(self, *_a, **_k):
            raise RuntimeError("meta exploded")

    result, rl, rest, _ = _make_call(product_meta=Exploding())
    assert result.status == STATUS_REST_FAILED
    assert "meta exploded" in (result.error or "")
    rest.limit_order_gtc.assert_not_called()
    assert rl.current_count(product_id="BTC-USDC", side="BUY", bucket_id=42, now=0.0) == 0
