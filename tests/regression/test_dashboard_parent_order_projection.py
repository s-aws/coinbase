"""Regression: dashboard parent-order reads must distinguish logical roots from placement rows."""

import pytest

import database.order_dashboard_helpers as helpers


@pytest.mark.regression
def test_get_all_parent_orders_projects_status_scope_and_root_status(monkeypatch):
    def fake_get_parent_orders():
        return [
            {
                "client_order_id": "root-1",
                "parent_order_id": None,
                "status": "FILLED",
                "price": 78145.0,
            },
            {
                "client_order_id": "child-1",
                "parent_order_id": "root-1",
                "status": "PENDING",
                "price": 78340.0,
            },
        ]

    monkeypatch.setattr(helpers, "get_parent_orders", fake_get_parent_orders)

    orders = helpers.get_all_parent_orders()
    by_id = {order["client_order_id"]: order for order in orders}

    assert by_id["root-1"]["is_root_order"] is True
    assert by_id["root-1"]["status_scope"] == "logical_root"
    assert by_id["root-1"]["placement_status"] == "FILLED"
    assert by_id["root-1"]["logical_root_status"] == "FILLED"
    assert by_id["root-1"]["logical_root_client_order_id"] == "root-1"

    assert by_id["child-1"]["is_root_order"] is False
    assert by_id["child-1"]["status_scope"] == "placement"
    assert by_id["child-1"]["placement_status"] == "PENDING"
    assert by_id["child-1"]["logical_root_status"] == "FILLED"
    assert by_id["child-1"]["logical_root_client_order_id"] == "root-1"


@pytest.mark.regression
def test_get_parent_order_by_client_id_projects_child_against_root(monkeypatch):
    def fake_get_parent_order(client_order_id):
        rows = {
            "child-1": {
                "client_order_id": "child-1",
                "parent_order_id": "root-1",
                "status": "PENDING",
            },
            "root-1": {
                "client_order_id": "root-1",
                "parent_order_id": None,
                "status": "FILLED",
            },
        }
        return rows.get(client_order_id)

    monkeypatch.setattr(helpers, "get_parent_order", fake_get_parent_order)

    order = helpers.get_parent_order_by_client_id("child-1")

    assert order is not None
    assert order["is_root_order"] is False
    assert order["status_scope"] == "placement"
    assert order["placement_status"] == "PENDING"
    assert order["logical_root_status"] == "FILLED"
    assert order["logical_root_client_order_id"] == "root-1"