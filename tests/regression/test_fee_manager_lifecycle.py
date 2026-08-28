"""Fee refresh publication remains stop-dominant during engine startup."""

from __future__ import annotations

import threading
from unittest.mock import Mock, patch

import pytest

from calculation.fee_manager import FeeManager
from core.enums import ProductType


pytestmark = pytest.mark.regression


def _manager() -> FeeManager:
    return FeeManager(Mock(name="rest_client"), log_callback=Mock())


def test_fee_manager_stop_before_start_is_terminal() -> None:
    manager = _manager()

    manager.stop()

    with patch("calculation.fee_manager.threading.Thread") as thread_factory:
        assert manager.start_periodic_refresh() is False
    thread_factory.assert_not_called()
    assert manager._running is False
    assert manager._shutdown_event.is_set()


def test_fee_manager_compatibility_start_remains_idempotent() -> None:
    manager = _manager()
    manager.refresh_now = Mock(return_value=True)

    try:
        assert manager.start() is True
        assert manager.start() is True
        manager.refresh_now.assert_called_once_with()
    finally:
        manager.stop()


def test_fee_manager_stop_during_initial_refresh_never_revives_worker() -> None:
    manager = _manager()
    refresh_entered = threading.Event()
    release_refresh = threading.Event()
    results = []

    def blocked_refresh() -> bool:
        refresh_entered.set()
        assert release_refresh.wait(timeout=1.0)
        return True

    manager.refresh_now = blocked_refresh
    starter = threading.Thread(target=lambda: results.append(manager.start()))
    starter.start()
    assert refresh_entered.wait(timeout=1.0)

    stopper = threading.Thread(target=manager.stop)
    stopper.start()
    stopper.join(timeout=0.5)
    assert not stopper.is_alive()
    assert manager._shutdown_event.is_set()
    assert manager._running is False

    release_refresh.set()
    starter.join(timeout=1.0)
    assert not starter.is_alive()
    assert results == [False]
    assert manager.start_periodic_refresh() is False
    assert manager._running is False


def test_stop_during_spot_refresh_prevents_future_request() -> None:
    manager = _manager()
    spot_entered = threading.Event()
    release_spot = threading.Event()
    requested_product_types = []
    results = []

    def blocked_schedule_refresh(product_type: ProductType) -> bool:
        requested_product_types.append(product_type)
        if product_type is ProductType.SPOT:
            spot_entered.set()
            assert release_spot.wait(timeout=1.0)
        return True

    manager._refresh_fee_schedule = blocked_schedule_refresh
    refresher = threading.Thread(
        target=lambda: results.append(manager.refresh_now())
    )
    refresher.start()
    assert spot_entered.wait(timeout=1.0)

    manager.stop()
    release_spot.set()
    refresher.join(timeout=1.0)

    assert not refresher.is_alive()
    assert results == [False]
    assert requested_product_types == [ProductType.SPOT]


def test_pre_stopped_refresh_performs_no_requests() -> None:
    manager = _manager()
    refresh_schedule = Mock(return_value=True)
    manager._refresh_fee_schedule = refresh_schedule
    manager.stop()

    assert manager.refresh_now() is False
    refresh_schedule.assert_not_called()
