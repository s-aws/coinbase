"""Regression contracts for actionable stealth-order visibility and labels."""

import re
from pathlib import Path

import pytest

from core.enums import StealthOrderStatus


REPO_ROOT = Path(__file__).resolve().parents[2]


def _manager_html() -> str:
    return (REPO_ROOT / "ui_stealth_orders_manager.html").read_text(
        encoding="utf-8"
    )


def _slice_between(source: str, start: str, end: str) -> str:
    start_index = source.index(start)
    return source[start_index:source.index(end, start_index)]


@pytest.mark.regression
def test_manager_uses_one_active_status_predicate_for_visibility_and_actions():
    html = _manager_html()
    predicate = re.search(
        r"function isActiveStealthOrder\(order\)\s*\{"
        r"\s*return\s*\[([^\]]+)\]\.includes\(order\.status\)"
        r"\s*\|\| isExchangeCancellationPending\(order\);\s*\}",
        html,
    )
    assert predicate is not None, "Missing shared active-order predicate"
    statuses = re.findall(r"['\"]([A-Z_]+)['\"]", predicate.group(1))
    expected = {
        StealthOrderStatus.HIDDEN.value,
        StealthOrderStatus.PENDING.value,
        StealthOrderStatus.TRIGGERED.value,
        StealthOrderStatus.REVEALED.value,
    }
    assert set(statuses) == expected
    assert len(statuses) == len(expected)

    table = _slice_between(html, "function updateOrdersTable()", "function updateStats()")
    eligibility = _slice_between(
        table,
        "const filteredParentOrders = parentOrders.filter(",
        "// Render function for order row",
    )
    assert "const isParentActive = isActiveStealthOrder(parentOrder);" in eligibility
    assert "const hasActiveChild = children.some(isActiveStealthOrder);" in eligibility
    assert "return isParentActive || hasActiveChild;" in eligibility
    assert "order.anchor_repricing_policy_json.enabled && isActiveStealthOrder(order)" in table

    stats = _slice_between(html, "function updateStats()", "function updateConditionFields()")
    assert "const active = orders.filter(isActiveStealthOrder);" in stats


@pytest.mark.regression
def test_manager_preserves_group_history_and_handles_no_visible_groups():
    html = _manager_html()
    table = _slice_between(html, "function updateOrdersTable()", "function updateStats()")
    assert "const parentOrders = orders.filter(o => !o.parent_order_id);" in table
    assert "orders.filter(o => o.parent_order_id).forEach(childOrder => {" in table
    assert "childOrdersByParent[childOrder.parent_order_id].push(childOrder);" in table

    render_groups = _slice_between(
        table,
        "filteredParentOrders.forEach(parentOrder => {",
        "tbody.innerHTML = html;",
    )
    assert "html += renderOrderRow(parentOrder, false);" in render_groups
    assert "childOrdersByParent[parentOrder.stealth_order_id].forEach(childOrder => {" in render_groups
    assert "html += renderOrderRow(childOrder, true, parentOrder.stealth_order_id);" in render_groups
    assert ".filter(" not in render_groups

    empty_state = _slice_between(
        table,
        "if (filteredParentOrders.length === 0)",
        "// Render function for order row",
    )
    assert table.index("const filteredParentOrders =") < table.index(empty_state)
    assert 'colspan="12"' in empty_state
    assert "No active stealth orders" in empty_state
    assert "return;" in empty_state
    assert "if (orders.length === 0)" not in table


@pytest.mark.regression
def test_rehide_action_restarts_same_order_without_creating_a_duplicate():
    html = _manager_html()
    assert re.search(r"\bhideOrder\s*\(", html) is None
    assert re.search(r"\bduplicateOrder\s*\(", html) is None
    assert re.search(r">\s*Hide\s*</button>", html) is None
    button = re.search(
        r'<button\b[^\n]*onclick="rehideOrder\([^\n]*>\s*Rehide\s*</button>',
        html,
    )
    assert button is not None
    assert "rearmPending" in button.group(0)
    assert "Number(order.executed_size) > 0" in button.group(0)
    assert "'disabled'" in button.group(0)

    rehide = _slice_between(html, "function rehideOrder(orderID)", "function repriceNow(orderID)")
    confirmation = re.search(r"if \(!confirm\(`([^`]+)`\)\)", rehide)
    assert confirmation is not None
    warning = confirmation.group(1).lower()
    for phrase in ("withdrawn", "same order", "reveal again", "satisfied"):
        assert phrase in warning
    assert 'type: "rehide_stealth_order"' in rehide
    assert "stealth_order_id: orderID" in rehide
    assert "order.status !== 'REVEALED'" in rehide
    assert "isStealthRearmPending(order)" in rehide
    assert "Number(order.executed_size) > 0" in rehide
    assert "placementClientOrderId: (order.anchor_repricing_state_json || {}).active_placement_client_order_id" in rehide
    assert "order.active_placement_client_order_id" not in html
    assert "sendCreateStealthOrderMessage" not in rehide
    assert "create_stealth_order" not in rehide
    assert "cancel_stealth_order" not in rehide
    assert ".status =" not in rehide

    create_message = _slice_between(
        html,
        "function sendCreateStealthOrderMessage(orderData)",
        "function isStealthRearmPending(order)",
    )
    assert 'type: "create_stealth_order"' in create_message
    assert "order: orderData" in create_message


@pytest.mark.regression
def test_rehide_result_waits_for_authoritative_state_and_guards_conflicting_actions():
    html = _manager_html()
    result_handler = _slice_between(
        html,
        '} else if (data.type === "stealth_order_rehide_result")',
        '} else if (data.type === "reprice_now_result")',
    )
    assert "data.accepted ? 'info' : 'error'" in result_handler
    assert "type: 'request_stealth_orders'" in result_handler
    assert ".status =" not in result_handler
    assert "ordersData[" not in result_handler
    assert 'data.type === "admission_rejected"' in result_handler
    assert "if (request) request.accepted = true" in result_handler

    snapshot_handler = _slice_between(
        html,
        '} else if (data.type === "stealth_orders_snapshot")',
        '} else if (data.type === "stealth_order_created")',
    )
    assert "if (request.accepted && progressed) pendingRehideRequests.delete(sid)" in snapshot_handler
    assert "(order.anchor_repricing_state_json || {}).active_placement_client_order_id !== request.placementClientOrderId" in snapshot_handler
    assert "order.anchor_repricing_state_json.pending_rearm" in snapshot_handler
    assert "pendingRehideRequests.clear()" not in snapshot_handler

    pending_guard = _slice_between(
        html, "function isStealthRearmPending(order)", "function rehideOrder(orderID)"
    )
    assert "pendingRehideRequests.has(order.stealth_order_id)" in pending_guard
    assert "order.anchor_repricing_state_json.pending_rearm" in pending_guard

    table = _slice_between(html, "function updateOrdersTable()", "function updateStats()")
    for css_class in ("move-btn", "reprice-btn", "edit-btn"):
        button = next(line for line in table.splitlines() if f'class="{css_class}"' in line)
        assert "rearmPending ? 'disabled' : ''" in button
    cancel_button = next(line for line in table.splitlines() if 'class="cancel-btn"' in line)
    assert "cancellationRequested ? 'disabled' : ''" in cancel_button


@pytest.mark.regression
def test_operator_cancellation_is_pending_authoritative_and_can_supersede_rehide():
    html = _manager_html()
    handler = _slice_between(html, '} else if (data.type === "stealth_order_cancel_result")',
                             '} else if (data.type === "stealth_orders_cleared")')
    assert "if (data.order) ordersData[data.stealth_order_id] = data.order" in handler
    assert ".status =" not in handler
    assert "ordersData = {}" not in handler
    assert "stealth_orders_clear_result" in handler
    assert "type: 'request_stealth_orders'" in handler
    cancel = _slice_between(html, "function cancelOrder(orderID)", "function sendCreateStealthOrderMessage")
    assert "isOperatorCancellationRequested(order)" in cancel
    assert "isStealthRearmPending(order)" not in cancel
    assert "No cancellation follow-up" in cancel
    assert "pendingCancelRequests.clear()" in _slice_between(html, "ws.onclose =", "ws.onerror =")
    pending = _slice_between(html, "function isExchangeCancellationPending(order)", "function updateOrdersTable()")
    for field in ("operator_cancel_requested_at", "pending_rearm", "active_placement_client_order_id", "revealed_size", "executed_size"):
        assert field in pending
    assert "state.pending_rearm.return_to_hidden === false" in pending
    assert "['CANCELLED', 'EXECUTED', 'ERROR'].includes(order.status)" in pending
    assert "CANCEL PENDING" in html
