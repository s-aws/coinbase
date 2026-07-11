from __future__ import annotations

import uuid
from threading import RLock
from types import SimpleNamespace

import database.order as order_db
import pytest
from core.enums import OrderOwnershipProvenance, OrderStatus, StandingPriceLimitPolicy
from core.order_engine import OrderEngine


ROOT_ID = "880e8400-e29b-41d4-a716-446655440000"
TEST_PORTFOLIO_ID = "11111111-2222-4333-8444-555555555555"


def _engine(*, persisted_row=None) -> OrderEngine:
    engine = OrderEngine.__new__(OrderEngine)
    engine.orderbook = SimpleNamespace(parent_order_ids={}, child_order_ids={})
    engine.orderbook_lock = RLock()
    engine.db_module = SimpleNamespace(
        get_parent_order=lambda _client_order_id: persisted_row,
    )
    return engine


def test_ownership_and_standing_policy_enums_are_stable() -> None:
    assert OrderOwnershipProvenance.ADMIN_MANUAL_ROOT.value == "ADMIN_MANUAL_ROOT"
    assert (
        OrderOwnershipProvenance.EXTERNAL_WS_OBSERVED.value
        == "EXTERNAL_WS_OBSERVED"
    )
    assert (
        OrderOwnershipProvenance.ADMIN_FILL_FOLLOW_UP.value
        == "ADMIN_FILL_FOLLOW_UP"
    )
    assert StandingPriceLimitPolicy.ADMIN_TEST_PROFILE.value == "admin_test_profile"
    assert OrderStatus.SUBMISSION_UNKNOWN.value == "SUBMISSION_UNKNOWN"
    assert OrderStatus.SUBMITTED.value == "SUBMITTED"


@pytest.mark.parametrize(
    ("provenance", "expected_external"),
    [
        (OrderOwnershipProvenance.ADMIN_MANUAL_ROOT.value, False),
        (OrderOwnershipProvenance.EXTERNAL_WS_OBSERVED.value, True),
        (None, True),
        ("UNKNOWN_LEGACY_VALUE", True),
    ],
)
def test_direct_root_automation_fails_closed_without_admin_provenance(
    provenance,
    expected_external,
) -> None:
    engine = _engine()
    engine.orderbook.parent_order_ids[ROOT_ID] = {
        "orders": [],
        "ownership_provenance": provenance,
    }

    assert engine._is_external_order(ROOT_ID) is expected_external


def test_admin_fill_child_is_not_misclassified_as_an_admin_direct_root() -> None:
    engine = _engine()
    engine.orderbook.parent_order_ids[ROOT_ID] = {
        "orders": ["child-id"],
        "ownership_provenance": (
            OrderOwnershipProvenance.ADMIN_MANUAL_ROOT.value
        ),
    }
    engine.orderbook.child_order_ids["child-id"] = ROOT_ID

    assert engine._is_admin_manual_root(ROOT_ID) is True
    assert engine._is_admin_manual_root("child-id") is False


def test_restart_hydration_preserves_external_provenance() -> None:
    engine = _engine(
        persisted_row={
            "id": 7,
            "client_order_id": ROOT_ID,
            "parent_order_id": None,
            "target_movement": "0.001",
            "target_movement_type": "P",
            "max_order_replacement": 11,
            "current_order_replacement": 0,
            "allow_partial_fills": False,
            "ownership_provenance": (
                OrderOwnershipProvenance.EXTERNAL_WS_OBSERVED.value
            ),
        }
    )

    assert engine._seed_parent_order_cache_from_db(ROOT_ID) is True
    assert engine.orderbook.parent_order_ids[ROOT_ID]["ownership_provenance"] == (
        OrderOwnershipProvenance.EXTERNAL_WS_OBSERVED.value
    )
    assert engine._is_external_order(ROOT_ID) is True


def test_bulk_reconciliation_preserves_admin_root_provenance(monkeypatch) -> None:
    engine = _engine()
    expected_parent = {
        "parent_id": 7,
        "orders": [],
        "target_movement": {"movement": 0.001, "type": "P"},
        "max_order_replacement": 11,
        "current_order_replacement": 0,
        "allow_partial_fills": False,
        "retail_portfolio_id": TEST_PORTFOLIO_ID,
        "ownership_provenance": (
            OrderOwnershipProvenance.ADMIN_MANUAL_ROOT.value
        ),
    }
    stale_parent = dict(expected_parent)
    stale_parent["current_order_replacement"] = 1
    engine.orderbook.parent_order_ids[ROOT_ID] = stale_parent

    def atomic_replace_links(new_parents, new_children):
        engine.orderbook.parent_order_ids = new_parents
        engine.orderbook.child_order_ids = new_children

    engine.orderbook.atomic_replace_links = atomic_replace_links
    engine.db_module = SimpleNamespace(
        get_parent_orders=lambda: [
            {
                "id": 7,
                "client_order_id": ROOT_ID,
                "target_movement": "0.001",
                "target_movement_type": "P",
                "max_order_replacement": 11,
                "current_order_replacement": 0,
                "allow_partial_fills": False,
                "retail_portfolio_id": TEST_PORTFOLIO_ID,
                "ownership_provenance": (
                    OrderOwnershipProvenance.ADMIN_MANUAL_ROOT.value
                ),
            }
        ],
    )
    engine._reconcile_diff_last_emit_monotonic = None
    engine._last_reconciled_counts = None
    engine.log_message = lambda *_args, **_kwargs: None
    monkeypatch.setattr(
        order_db,
        "get_stealth_children_for_parent",
        lambda _parent_client_order_id: [],
    )

    assert engine.load_parent_child_order_ids() is True
    assert engine.orderbook.parent_order_ids[ROOT_ID] == expected_parent
    assert engine._is_admin_manual_root(ROOT_ID) is True


def test_unknown_ws_order_is_registered_as_external_observation() -> None:
    engine = _engine()
    captured = {}
    engine._seed_parent_order_cache_from_db = lambda _client_order_id: False

    def resolve(client_order_id, **kwargs):
        captured.update(kwargs)
        engine.orderbook.parent_order_ids[client_order_id] = {
            "orders": [],
            "ownership_provenance": kwargs.get("ownership_provenance"),
        }
        return True, client_order_id

    engine.resolve_parent_client_order_id = resolve
    engine._ensure_order_parent_row_exists(
        {
            "client_order_id": ROOT_ID,
            "product_id": "BTC-USDC",
            "order_side": "BUY",
            "status": OrderStatus.OPEN.value,
        }
    )

    assert captured["ownership_provenance"] == (
        OrderOwnershipProvenance.EXTERNAL_WS_OBSERVED
    )
    assert engine._is_external_order(ROOT_ID) is True


def test_insert_order_parent_rejects_reused_admin_identity_with_changed_facts(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        order_db,
        "get_parent_order",
        lambda _client_order_id: {
            "id": 7,
            "client_order_id": ROOT_ID,
            "product_id": "ETH-USDC",
            "side": "BUY",
            "size": "0.01",
            "price": "100",
            "parent_order_id": None,
            "ownership_provenance": (
                OrderOwnershipProvenance.ADMIN_MANUAL_ROOT.value
            ),
            "retail_portfolio_id": TEST_PORTFOLIO_ID,
            "correlation_id": "corr-root",
            "audit_id": "audit-root",
        },
    )

    with pytest.raises(order_db.OrderPersistenceError, match="immutable facts"):
        order_db.insert_order_parent(
            client_order_id=ROOT_ID,
            product_id="BTC-USDC",
            side="BUY",
            size=0.01,
            price=100,
            target_movement=0.001,
            ownership_provenance=(
                OrderOwnershipProvenance.ADMIN_MANUAL_ROOT
            ),
            retail_portfolio_id=TEST_PORTFOLIO_ID,
            correlation_id="corr-root",
            audit_id="audit-root",
        )


class _QueryDb:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def execute_query(self, query, params=()):
        self.calls.append((" ".join(query.split()), tuple(params)))
        return self.rows


def test_unresolved_admin_root_query_is_profile_scoped_and_root_only(
    monkeypatch,
) -> None:
    expected = [{"client_order_id": ROOT_ID, "status": "SUBMISSION_UNKNOWN"}]
    db = _QueryDb(expected)
    monkeypatch.setattr(order_db, "DB_CLIENT", db)

    rows = order_db.get_unresolved_admin_manual_root_submissions(
        TEST_PORTFOLIO_ID
    )

    assert rows == expected
    assert order_db.has_unresolved_admin_manual_root_submission(
        TEST_PORTFOLIO_ID
    ) is True
    query, params = db.calls[0]
    assert "parent_order_id IS NULL" in query
    assert "ownership_provenance = %s" in query
    assert "UPPER(status) NOT IN" in query
    assert params[0] == TEST_PORTFOLIO_ID
    assert params[1] == OrderOwnershipProvenance.ADMIN_MANUAL_ROOT.value


@pytest.mark.integration
@pytest.mark.serial
def test_unresolved_admin_root_query_round_trips_test_database() -> None:
    order_db.create_order_parent_table()
    portfolio_id = str(uuid.uuid4())
    unresolved_id = str(uuid.uuid4())
    terminal_id = str(uuid.uuid4())
    external_id = str(uuid.uuid4())

    try:
        for client_order_id, status, provenance in (
            (
                unresolved_id,
                OrderStatus.SUBMISSION_UNKNOWN.value,
                OrderOwnershipProvenance.ADMIN_MANUAL_ROOT,
            ),
            (
                terminal_id,
                OrderStatus.FILLED.value,
                OrderOwnershipProvenance.ADMIN_MANUAL_ROOT,
            ),
            (
                external_id,
                OrderStatus.PENDING.value,
                OrderOwnershipProvenance.EXTERNAL_WS_OBSERVED,
            ),
        ):
            order_db.insert_order_parent(
                client_order_id=client_order_id,
                product_id="BTC-USDC",
                side="BUY",
                size=0.01,
                price=100,
                target_movement=0.001,
                status=status,
                ownership_provenance=provenance,
                retail_portfolio_id=portfolio_id,
                correlation_id=f"corr-{client_order_id}",
                audit_id=f"audit-{client_order_id}",
            )

        rows = order_db.get_unresolved_admin_manual_root_submissions(
            portfolio_id
        )

        assert [str(row["client_order_id"]) for row in rows] == [unresolved_id]
        assert order_db.has_unresolved_admin_manual_root_submission(
            portfolio_id
        ) is True

        order_db.update_order_parent_status(
            unresolved_id,
            OrderStatus.FAILED.value,
        )
        assert order_db.has_unresolved_admin_manual_root_submission(
            portfolio_id
        ) is False
    finally:
        with order_db.DB_CLIENT.get_cursor() as cursor:
            cursor.execute(
                "DELETE FROM order_parent WHERE client_order_id IN (%s, %s, %s)",
                (unresolved_id, terminal_id, external_id),
            )
