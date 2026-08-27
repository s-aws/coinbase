"""Startup must distinguish an empty stealth table from failed hydration."""

from core.stealth_order_manager import StealthOrderManager


class _HydrationDB:
    def __init__(self, *, rows=(), error=None):
        self.rows = list(rows)
        self.error = error

    def execute_query(self, _sql):
        if self.error is not None:
            raise self.error
        return list(self.rows)


def _manager(db):
    return StealthOrderManager(
        db,
        log_callback=lambda _level, _message: None,
    )


def test_empty_table_is_a_completed_hydration() -> None:
    manager = _manager(_HydrationDB())

    assert manager.load_all_active_orders_from_db() == 0
    assert manager._last_hydration_complete is True


def test_batch_query_failure_is_not_an_empty_completed_hydration() -> None:
    manager = _manager(
        _HydrationDB(error=RuntimeError("database unavailable"))
    )

    assert manager.load_all_active_orders_from_db() == 0
    assert manager._last_hydration_complete is False


def test_malformed_row_makes_hydration_partial_and_unready() -> None:
    manager = _manager(
        _HydrationDB(rows=({"stealth_order_id": "malformed-row"},))
    )

    assert manager.load_all_active_orders_from_db() == 0
    assert manager._last_hydration_complete is False
