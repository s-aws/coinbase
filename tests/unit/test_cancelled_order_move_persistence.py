"""Contract tests for cancelled-parent move persistence composition."""

from unittest.mock import MagicMock

from business import move_manager as move_manager_module
from core.order_engine import OrderEngine
from database import execution_persistence
from database import order as order_db


def test_database_adapter_delegates_cancelled_move_capability(monkeypatch):
    db_client = object()
    adapter = execution_persistence.DatabaseOrderPersistenceAdapter(db_client)
    helpers = {
        "get_parent_order": MagicMock(return_value={"id": 1}),
        "insert_order_parent": MagicMock(return_value=2),
        "insert_order_move": MagicMock(return_value=3),
        "get_order_move": MagicMock(return_value={"id": 3}),
        "get_order_moves_by_new_parent": MagicMock(return_value=[{"id": 3}]),
        "get_pending_move": MagicMock(return_value={"id": 4}),
        "has_pending_move": MagicMock(return_value=True),
        "create_pending_move": MagicMock(return_value=4),
        "finalize_pending_move": MagicMock(return_value=4),
    }
    for name, helper in helpers.items():
        monkeypatch.setattr(execution_persistence.order_db, name, helper)

    assert adapter.get_parent_order("original") == {"id": 1}
    assert adapter.create_parent_order(
        client_order_id="replacement",
        product_id="BTC-USD",
        side="BUY",
        size=1.0,
        price=100.0,
        target_movement=0.01,
        target_movement_type="P",
        max_order_replacement=3,
        current_order_replacement=0,
        status="PENDING",
    ) == 2
    assert adapter.record_order_move(
        original_parent_client_order_id="original",
        new_parent_client_order_id="replacement",
        reason="cancelled_move",
        notes=None,
    ) == 3
    assert adapter.get_order_move("original") == {"id": 3}
    assert adapter.list_order_moves_by_new_parent("replacement") == [{"id": 3}]
    assert adapter.get_pending_move("original") == {"id": 4}
    assert adapter.has_pending_move("original") is True
    assert adapter.create_pending_move(
        original_parent_client_order_id="original",
        new_order_details={"price": 100.0},
        reason="scheduled",
        notes="operator",
    ) == 4
    assert adapter.finalize_pending_move(
        pending_move_id=4,
        original_parent_client_order_id="original",
        new_parent_client_order_id="replacement",
        product_id="BTC-USD",
        side="BUY",
        size=1.0,
        price=100.0,
        target_movement=0.01,
        target_movement_type="P",
        max_order_replacement=3,
        status="PENDING",
    ) == 4

    helpers["get_parent_order"].assert_called_once_with(
        "original",
        db_client=db_client,
    )
    helpers["insert_order_parent"].assert_called_once_with(
        client_order_id="replacement",
        product_id="BTC-USD",
        side="BUY",
        size=1.0,
        price=100.0,
        target_movement=0.01,
        target_movement_type="P",
        max_order_replacement=3,
        current_order_replacement=0,
        status="PENDING",
        db_client=db_client,
    )
    helpers["insert_order_move"].assert_called_once_with(
        original_parent_client_order_id="original",
        new_parent_client_order_id="replacement",
        reason="cancelled_move",
        notes=None,
        db_client=db_client,
    )
    helpers["get_order_move"].assert_called_once_with(
        "original",
        db_client=db_client,
    )
    helpers["get_order_moves_by_new_parent"].assert_called_once_with(
        "replacement",
        db_client=db_client,
    )
    helpers["get_pending_move"].assert_called_once_with(
        "original",
        db_client=db_client,
    )
    helpers["has_pending_move"].assert_called_once_with(
        "original",
        db_client=db_client,
    )
    helpers["create_pending_move"].assert_called_once_with(
        original_parent_client_order_id="original",
        new_order_details={"price": 100.0},
        reason="scheduled",
        notes="operator",
        db_client=db_client,
    )
    helpers["finalize_pending_move"].assert_called_once_with(
        pending_move_id=4,
        original_parent_client_order_id="original",
        new_parent_client_order_id="replacement",
        product_id="BTC-USD",
        side="BUY",
        size=1.0,
        price=100.0,
        target_movement=0.01,
        target_movement_type="P",
        max_order_replacement=3,
        status="PENDING",
        db_client=db_client,
    )


def test_cancelled_move_helpers_honor_explicit_database_client(monkeypatch):
    explicit_client = MagicMock()
    compatibility_client = MagicMock()
    monkeypatch.setattr(order_db, "DB_CLIENT", compatibility_client)

    explicit_client.execute_query.side_effect = [[], [{"id": 1}]]
    assert order_db.insert_order_parent(
        client_order_id="replacement",
        product_id="BTC-USD",
        side="BUY",
        size=1.0,
        price=100.0,
        target_movement=0.01,
        db_client=explicit_client,
    ) == 1
    assert explicit_client.execute_query.call_count == 2

    explicit_client.reset_mock()
    explicit_client.execute_query.side_effect = None
    explicit_client.execute_query.return_value = [{"id": 2}]
    assert order_db.insert_order_move(
        "original",
        "replacement",
        db_client=explicit_client,
    ) == 2

    explicit_client.reset_mock()
    explicit_client.execute_query.return_value = [{"id": 3}]
    assert order_db.get_order_move(
        "original",
        db_client=explicit_client,
    ) == {"id": 3}

    explicit_client.reset_mock()
    explicit_client.execute_query.return_value = [{"id": 4}]
    assert order_db.get_order_moves_by_new_parent(
        "replacement",
        db_client=explicit_client,
    ) == [{"id": 4}]

    explicit_client.reset_mock()
    explicit_client.execute_query.return_value = [{"id": 5}]
    assert order_db.get_pending_move(
        "original",
        db_client=explicit_client,
    ) == {"id": 5}

    explicit_client.reset_mock()
    explicit_client.execute_query.return_value = []
    assert order_db.has_pending_move(
        "original",
        db_client=explicit_client,
    ) is False

    explicit_client.reset_mock()
    explicit_client.execute_query.return_value = [{"id": 6}]
    assert order_db.create_pending_move(
        "original",
        {"price": 100.0},
        db_client=explicit_client,
    ) == 6

    explicit_client.reset_mock()
    explicit_client.execute_query.return_value = [{"id": 6}]
    assert order_db.finalize_pending_move(
        pending_move_id=6,
        original_parent_client_order_id="original",
        new_parent_client_order_id="replacement",
        product_id="BTC-USD",
        side="BUY",
        size=1.0,
        price=100.0,
        target_movement=0.01,
        db_client=explicit_client,
    ) == 6

    compatibility_client.execute_query.assert_not_called()
    compatibility_client.execute_update.assert_not_called()


def test_create_pending_move_database_error_is_not_masked(monkeypatch):
    explicit_client = MagicMock()
    explicit_client.execute_query.side_effect = RuntimeError("write failed")
    error_log = MagicMock()
    debug_log = MagicMock()
    monkeypatch.setattr(order_db.logger, "error", error_log)
    monkeypatch.setattr(order_db.logger, "debug", debug_log)

    result = order_db.create_pending_move(
        "original",
        {"price": 100.0},
        reason="scheduled",
        db_client=explicit_client,
    )

    assert result is None
    error_log.assert_called_once_with(
        "Error creating pending move original: RuntimeError: write failed"
    )
    debug_log.assert_called_once_with(
        "  Pending move details - new_order_details: {'price': 100.0}, "
        "reason: scheduled"
    )


def test_order_engine_builds_move_manager_with_injected_persistence(monkeypatch):
    orderbook = object()
    persistence = object()
    move_manager = object()
    factory = MagicMock(return_value=move_manager)
    monkeypatch.setattr(move_manager_module, "MoveManager", factory)
    engine = object.__new__(OrderEngine)
    engine.orderbook = orderbook
    engine.cancelled_move_persistence = persistence

    assert engine._new_move_manager() is move_manager
    factory.assert_called_once_with(orderbook, persistence=persistence)
