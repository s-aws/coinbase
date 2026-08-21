"""Tests for ``business.hotpoint_rate_limiter``."""

from __future__ import annotations

import pytest

from business.hotpoint_rate_limiter import HotpointRateLimiter


pytestmark = pytest.mark.regression


def _make(**overrides):
    defaults = dict(cap_n=3, window_seconds=60)
    defaults.update(overrides)
    return HotpointRateLimiter(**defaults)


def test_first_acquire_allowed():
    rl = _make()
    d = rl.try_acquire(product_id="X", side="BUY", bucket_id=1, now=0.0)
    assert d.allowed and d.current_count == 1 and d.cap == 3


def test_acquire_then_commit_counts_toward_cap():
    rl = _make(cap_n=2)
    d1 = rl.try_acquire(product_id="X", side="BUY", bucket_id=1, now=0.0)
    rl.commit(product_id="X", side="BUY", bucket_id=1, now=0.0)
    assert d1.allowed
    d2 = rl.try_acquire(product_id="X", side="BUY", bucket_id=1, now=1.0)
    rl.commit(product_id="X", side="BUY", bucket_id=1, now=1.0)
    assert d2.allowed
    d3 = rl.try_acquire(product_id="X", side="BUY", bucket_id=1, now=2.0)
    assert not d3.allowed and d3.reason == "cap_reached"


def test_in_flight_acquisitions_count_toward_cap():
    """Two acquires without commit must still consume the cap."""
    rl = _make(cap_n=2)
    rl.try_acquire(product_id="X", side="BUY", bucket_id=1, now=0.0)
    rl.try_acquire(product_id="X", side="BUY", bucket_id=1, now=0.1)
    d = rl.try_acquire(product_id="X", side="BUY", bucket_id=1, now=0.2)
    assert not d.allowed


def test_rollback_releases_slot():
    rl = _make(cap_n=1)
    d1 = rl.try_acquire(product_id="X", side="BUY", bucket_id=1, now=0.0)
    assert d1.allowed
    d2 = rl.try_acquire(product_id="X", side="BUY", bucket_id=1, now=0.1)
    assert not d2.allowed
    rl.rollback(product_id="X", side="BUY", bucket_id=1)
    d3 = rl.try_acquire(product_id="X", side="BUY", bucket_id=1, now=0.2)
    assert d3.allowed


def test_indeterminate_quarantine_blocks_entire_key_until_window_expires():
    rl = _make(cap_n=5, window_seconds=10)
    first = rl.try_acquire(product_id="X", side="BUY", bucket_id=1, now=0.0)
    assert first.allowed

    rl.quarantine(product_id="X", side="BUY", bucket_id=1, now=0.0)

    blocked = rl.try_acquire(product_id="X", side="BUY", bucket_id=1, now=9.9)
    assert blocked.allowed is False
    assert blocked.current_count == 5
    assert blocked.reason == "acceptance_indeterminate"
    allowed = rl.try_acquire(product_id="X", side="BUY", bucket_id=1, now=10.0)
    assert allowed.allowed is True


def test_window_expiry_evicts_old_placements():
    rl = _make(cap_n=2, window_seconds=10)
    rl.try_acquire(product_id="X", side="BUY", bucket_id=1, now=0.0)
    rl.commit(product_id="X", side="BUY", bucket_id=1, now=0.0)
    rl.try_acquire(product_id="X", side="BUY", bucket_id=1, now=1.0)
    rl.commit(product_id="X", side="BUY", bucket_id=1, now=1.0)
    # At t=11, the t=0 placement has aged out; cap allows one more.
    d = rl.try_acquire(product_id="X", side="BUY", bucket_id=1, now=11.0)
    assert d.allowed


def test_keys_are_independent():
    rl = _make(cap_n=1)
    rl.try_acquire(product_id="X", side="BUY", bucket_id=1, now=0.0)
    rl.commit(product_id="X", side="BUY", bucket_id=1, now=0.0)
    # Different side -> still allowed.
    d = rl.try_acquire(product_id="X", side="SELL", bucket_id=1, now=0.0)
    assert d.allowed
    # Different bucket -> still allowed.
    d2 = rl.try_acquire(product_id="X", side="BUY", bucket_id=2, now=0.0)
    assert d2.allowed
    # Different product -> still allowed.
    d3 = rl.try_acquire(product_id="Y", side="BUY", bucket_id=1, now=0.0)
    assert d3.allowed


def test_record_placement_bypasses_cap_for_hydration():
    rl = _make(cap_n=1)
    # Pretend we found 5 prior placements at startup. record_placement
    # does not check the cap.
    for ts in (0.0, 1.0, 2.0, 3.0, 4.0):
        rl.record_placement(product_id="X", side="BUY", bucket_id=1, at_epoch=ts)
    assert rl.current_count(product_id="X", side="BUY", bucket_id=1, now=5.0) == 5
    # New acquires now blocked because count > cap.
    d = rl.try_acquire(product_id="X", side="BUY", bucket_id=1, now=5.0)
    assert not d.allowed


def test_hydrate_loads_multiple_keys():
    rl = _make(cap_n=10, window_seconds=60)
    n = rl.hydrate([
        ("X", "BUY", 1, 0.0),
        ("X", "BUY", 1, 1.0),
        ("Y", "SELL", 7, 5.0),
    ])
    assert n == 3
    assert rl.current_count(product_id="X", side="BUY", bucket_id=1, now=2.0) == 2
    assert rl.current_count(product_id="Y", side="SELL", bucket_id=7, now=6.0) == 1


def test_commit_without_acquire_still_records():
    """Defensive: commit when nothing is in-flight just records.

    Avoids losing a placement if the in-flight bookkeeping is ever wrong.
    """
    rl = _make()
    rl.commit(product_id="X", side="BUY", bucket_id=1, now=0.0)
    assert rl.current_count(product_id="X", side="BUY", bucket_id=1, now=1.0) == 1


def test_rollback_when_nothing_in_flight_is_safe():
    rl = _make()
    # Should not raise or go negative.
    rl.rollback(product_id="X", side="BUY", bucket_id=1)
    assert rl.current_count(product_id="X", side="BUY", bucket_id=1, now=0.0) == 0


def test_constructor_validation():
    with pytest.raises(ValueError):
        HotpointRateLimiter(cap_n=0, window_seconds=10)
    with pytest.raises(ValueError):
        HotpointRateLimiter(cap_n=1, window_seconds=0)
