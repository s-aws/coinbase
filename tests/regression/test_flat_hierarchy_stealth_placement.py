"""Regression: flat-hierarchy rule must not be violated by stealth placements.

Background
----------
``agent.md`` states the rule plainly: every child order links to the **original
root**, never to an intermediate slice. There are NO grandchildren in the
``order_parent`` table.

On 2026-04-27 the production DB was found to contain three real grandchildren
(rows 7, 224, 225) — placement uuids whose ``parent_order_id`` pointed at a
stealth follow-up's ``stealth_order_id`` rather than at the chain root. Later
the same day, a fourth in-memory variant was found in three OrderEngine
``register_child_order`` call sites that registered stealth follow-ups under
the placement uuid that just settled (a child) instead of the chain root.

Root cause both times: the same two-line resolution was open-coded in six
separate places. Any one of them could (and did) silently regress.

Fix-by-design: a single module-level resolver
``core.stealth_order_manager.resolve_stealth_chain_root(stealth_order)``
encapsulates the rule. Every call site that needs the chain root MUST go
through it. These tests enforce that contract.
"""

from __future__ import annotations

import inspect
import re

import pytest

from core.order_engine import OrderEngine
from core.stealth_order_manager import (
    StealthOrderManager,
    resolve_stealth_chain_root,
)


def test_resolver_returns_self_for_root_stealth() -> None:
    root_stealth = {"stealth_order_id": "root-uuid", "parent_order_id": None}
    assert resolve_stealth_chain_root(root_stealth) == "root-uuid"


def test_resolver_returns_root_for_followup_stealth() -> None:
    follow_up = {
        "stealth_order_id": "follow-up-uuid",
        "parent_order_id": "root-uuid",
    }
    # Critical: returns "root-uuid", NOT "follow-up-uuid".
    assert resolve_stealth_chain_root(follow_up) == "root-uuid"


def test_resolver_handles_chain_of_followups() -> None:
    """Both follow-ups in a chain carry parent_order_id = root, so resolution
    is one hop, never recursive. If a future follow-up ever pointed at another
    follow-up (which would itself be a grandchild) this would surface as a
    real bug elsewhere — this test pins the one-hop contract."""

    follow_up_a = {"stealth_order_id": "fu-a", "parent_order_id": "root"}
    follow_up_b = {"stealth_order_id": "fu-b", "parent_order_id": "root"}
    assert resolve_stealth_chain_root(follow_up_a) == "root"
    assert resolve_stealth_chain_root(follow_up_b) == "root"


def test_resolver_raises_on_missing_stealth_order_id() -> None:
    """A dict with neither parent_order_id nor stealth_order_id is malformed;
    fail loudly at the boundary rather than silently returning None."""

    with pytest.raises(KeyError):
        resolve_stealth_chain_root({})


def test_stealth_order_manager_routes_through_canonical_resolver() -> None:
    """All ``insert_order_parent`` placement sites and the follow-up creation
    site in StealthOrderManager must call ``resolve_stealth_chain_root`` rather
    than open-coding the rule.
    """

    src = inspect.getsource(StealthOrderManager)

    # The manager must call the resolver at least 3 times: the two placement
    # insert sites (anchor reprice + reveal slice) and create_follow_up_stealth_order.
    call_count = src.count("resolve_stealth_chain_root(")
    assert call_count >= 3, (
        f"StealthOrderManager source contains only {call_count} call(s) to "
        "resolve_stealth_chain_root. Expected at least 3 (anchor reprice, "
        "reveal slice, create_follow_up_stealth_order). Did a site revert to "
        "open-coding `order.get('parent_order_id') or order['stealth_order_id']`?"
    )

    # Negative guard: no caller may inline the literal pattern again. This is
    # a hard line-based check; if you genuinely need the rule somewhere new,
    # call the resolver instead.
    forbidden_patterns = (
        'parent_order_id=order["stealth_order_id"]',
        "parent_order_id=order['stealth_order_id']",
        'order.get("parent_order_id") or order["stealth_order_id"]',
        "order.get('parent_order_id') or order['stealth_order_id']",
    )
    for pattern in forbidden_patterns:
        assert pattern not in src, (
            f"Found inlined flat-hierarchy resolution: `{pattern}`. "
            "Call resolve_stealth_chain_root(order) instead — that is the "
            "single source of truth for this rule."
        )


def test_order_engine_register_child_order_uses_resolver() -> None:
    """Every ``register_child_order(stealth_follow_up_id, ...)`` call in
    OrderEngine must pass a value produced by ``resolve_stealth_chain_root``.

    The placement uuid (``parent_client_order_id``) is itself a child of the
    root after the prior fix. Registering a follow-up under it would create
    an in-memory grandchild AND bump the wrong DB replacement counter.

    Production incident (2026-04-27): follow-up ``9363c96d`` was registered
    under placement ``400a06bd`` instead of root ``fa457f47``.
    """

    src = inspect.getsource(OrderEngine)

    # All three follow-up register sites must compute root via the resolver.
    follow_up_call_args = re.findall(
        r"register_child_order\(\s*stealth_follow_up_id\s*,\s*(\w+)\s*\)",
        src,
    )
    assert len(follow_up_call_args) >= 3, (
        f"Expected at least 3 register_child_order(stealth_follow_up_id, ...) "
        f"call sites, found {len(follow_up_call_args)}: {follow_up_call_args}"
    )

    forbidden_arg = "parent_client_order_id"
    bad = [arg for arg in follow_up_call_args if arg == forbidden_arg]
    assert not bad, (
        f"Found {len(bad)} register_child_order(stealth_follow_up_id, "
        f"parent_client_order_id) call(s). `parent_client_order_id` is the "
        f"placement uuid that just settled — it is itself a child. "
        f"Use resolve_stealth_chain_root(original_stealth_order) and pass that."
    )

    # And the resolver must actually be invoked in OrderEngine — at least
    # once for each follow-up site plus once in _register_stealth_placement_under_root.
    resolver_invocations = src.count("resolve_stealth_chain_root(")
    assert resolver_invocations >= 4, (
        f"OrderEngine source invokes resolve_stealth_chain_root only "
        f"{resolver_invocations} time(s). Expected at least 4 (3 follow-up "
        f"register sites + _register_stealth_placement_under_root)."
    )
