"""Regression: ``create_follow_up_stealth_order`` actually applies the
fingerprint-hiding retreat from the inherited ``RepricingPolicy``.

Pre-fix bug: the helper ``RepricingPolicy.compute_follow_up_price`` was
defined and unit-tested but the call site in
``StealthOrderManager.create_follow_up_stealth_order`` still passed the
caller's raw ``limit_price`` straight into ``create_stealth_order``,
making the retreat dead code (same shape as the
``effective_start_price`` bug we found in ``order.py``).

These tests pin:

* When the inherited policy has a non-zero retreat distance, the
  follow-up's ``limit_price`` arrives at ``create_stealth_order``
  RETREATED relative to the caller's ``limit_price``.
* The follow-up's stealth_order_id is pre-generated and passed through
  AS the jitter seed -- proves audit-replayability.
* When the inherited policy is disabled (anchor repricing turned off
  by the operator), no retreat is applied -- pinning the design choice
  that disabled-policy short-circuits retreat too.
* The audit trail (the retreat values used) appears in the notes
  string so post-mortems can answer \"what retreat was applied to that
  follow-up?\" without reconstructing it from coid + policy.
"""

from unittest.mock import Mock

import pytest

from core.models import RepricingPolicy
from core.stealth_order_manager import StealthOrderManager


def _build_manager_with_filled_child(retreat_distance: float, retreat_jitter: float):
    """Build a StealthOrderManager with one filled child whose policy
    carries the requested retreat configuration."""
    manager = StealthOrderManager(db_client=None)

    policy = {
        "enabled": True,
        "target_distance": 0.001,
        "max_distance": 0.005,
        "follow_up_retreat_distance": retreat_distance,
        "follow_up_retreat_jitter": retreat_jitter,
        "inherit_to_follow_ups": True,
    }

    root_parent_id = "root-parent-aaa"
    filled_child_id = "filled-child-bbb"
    manager.in_memory_orders[filled_child_id] = {
        "stealth_order_id": filled_child_id,
        "product_id": "BIP-20DEC30-CDE",
        "side": "SELL",
        "total_size": 1.0,
        "limit_price": 50_000.0,
        "reveal_condition_json": {"type": "time_delay", "delay_seconds": 0},
        "sizing_strategy_json": {"type": "fixed"},
        "reveal_pricing_policy": "configured_limit",
        "follow_up_reveal_direction": "opposite",
        "parent_order_id": root_parent_id,
        "anchor_repricing_policy_json": policy,
    }
    return manager, filled_child_id


@pytest.mark.regression
def test_follow_up_creation_applies_retreat_from_inherited_policy():
    """Non-zero retreat MUST land at create_stealth_order, not be dropped."""
    manager, filled_child_id = _build_manager_with_filled_child(
        retreat_distance=0.005,  # 50 bps
        retreat_jitter=0.0,      # deterministic for assertion
    )
    create_mock = Mock(return_value="new-follow-up-ccc")
    manager.create_stealth_order = create_mock

    manager.create_follow_up_stealth_order(
        original_stealth_order_id=filled_child_id,
        side="BUY",
        total_size=1.0,
        limit_price=50_000.0,
    )

    create_mock.assert_called_once()
    kwargs = create_mock.call_args.kwargs
    sent_price = kwargs["limit_price"]
    # BUY retreat: posted price must be LOWER than the caller's anchor.
    # 50000 * (1 - 0.005) = 49750. Allow a bit of room for tick-alignment
    # (BIP-20DEC30-CDE price_increment is "5" per products.json so no shift here,
    # but other products tick differently).
    assert sent_price < 50_000.0
    assert sent_price == pytest.approx(49_750.0, abs=1.0)


@pytest.mark.regression
def test_follow_up_creation_seeds_jitter_with_pregenerated_coid():
    """The follow-up stealth_order_id must be pre-generated AND passed
    through to create_stealth_order. This proves the same UUID is the
    jitter seed AND the persisted coid (audit-replayable)."""
    manager, filled_child_id = _build_manager_with_filled_child(
        retreat_distance=0.005,
        retreat_jitter=0.5,  # exercises jitter path
    )
    create_mock = Mock(return_value="ignored")
    manager.create_stealth_order = create_mock

    manager.create_follow_up_stealth_order(
        original_stealth_order_id=filled_child_id,
        side="BUY",
        total_size=1.0,
        limit_price=50_000.0,
    )

    kwargs = create_mock.call_args.kwargs
    assert kwargs.get("stealth_order_id"), (
        "create_follow_up_stealth_order must pre-generate and forward "
        "stealth_order_id; otherwise jitter seed != persisted coid and "
        "audit replay is broken."
    )


@pytest.mark.regression
def test_disabled_policy_skips_retreat_in_follow_up_creation():
    """If anchor-repricing is disabled, no retreat is applied (mirrors
    the helper's short-circuit on ``not self.enabled``)."""
    manager = StealthOrderManager(db_client=None)
    # Disabled policy via explicit enabled=False.
    manager.in_memory_orders["filled-child"] = {
        "stealth_order_id": "filled-child",
        "product_id": "BIP-20DEC30-CDE",
        "side": "SELL",
        "total_size": 1.0,
        "limit_price": 50_000.0,
        "reveal_condition_json": {"type": "time_delay", "delay_seconds": 0},
        "sizing_strategy_json": {"type": "fixed"},
        "reveal_pricing_policy": "configured_limit",
        "follow_up_reveal_direction": "opposite",
        "parent_order_id": "root-aaa",
        "anchor_repricing_policy_json": {"enabled": False},
    }
    create_mock = Mock(return_value="ignored")
    manager.create_stealth_order = create_mock

    manager.create_follow_up_stealth_order(
        original_stealth_order_id="filled-child",
        side="BUY",
        total_size=1.0,
        limit_price=50_000.0,
    )

    kwargs = create_mock.call_args.kwargs
    # No retreat -> price equals what the caller passed (still tick-aligned
    # by create_stealth_order downstream, but not retreated by us).
    assert kwargs["limit_price"] == 50_000.0


@pytest.mark.regression
def test_follow_up_audit_trail_includes_retreat_values():
    """Post-mortem must be able to answer 'what retreat was applied?'
    The notes field is the only structured channel that survives
    end-to-end through create_stealth_order without a schema change."""
    manager, filled_child_id = _build_manager_with_filled_child(
        retreat_distance=0.005,
        retreat_jitter=0.0,
    )
    create_mock = Mock(return_value="new-follow-up")
    manager.create_stealth_order = create_mock

    manager.create_follow_up_stealth_order(
        original_stealth_order_id=filled_child_id,
        side="BUY",
        total_size=1.0,
        limit_price=50_000.0,
        notes="user-supplied-context",
    )

    notes = create_mock.call_args.kwargs["notes"]
    assert "user-supplied-context" in notes
    assert "retreat" in notes
    assert "0.005" in notes  # distance value visible
    assert "50000" in notes  # anchor visible


@pytest.mark.regression
def test_follow_up_structured_audit_dict_populated_on_in_memory_order():
    """The structured ``follow_up_audit`` dict on the in-memory order
    is the programmatic counterpart to the notes string. Dashboard +
    debugging tools should consume this, not parse notes."""
    manager, filled_child_id = _build_manager_with_filled_child(
        retreat_distance=0.005,
        retreat_jitter=0.0,
    )
    new_id_holder = {}
    # Real create_stealth_order would register the in-memory order; we
    # mock it to do that registration itself so the post-create
    # _get_stealth_order lookup finds something to attach audit onto.
    # The production code pre-generates the stealth_order_id in
    # create_follow_up_stealth_order and passes it through; we honor that
    # so the seed-equals-coid invariant holds.
    def fake_create(**kwargs):
        new_id = kwargs["stealth_order_id"]
        new_id_holder["id"] = new_id
        manager.in_memory_orders[new_id] = {
            "stealth_order_id": new_id,
            "product_id": kwargs["product_id"],
            "side": kwargs["side"],
            "total_size": kwargs["total_size"],
            "limit_price": kwargs["limit_price"],
        }
        return new_id

    manager.create_stealth_order = fake_create
    manager.create_follow_up_stealth_order(
        original_stealth_order_id=filled_child_id,
        side="BUY",
        total_size=1.0,
        limit_price=50_000.0,
    )

    new_id = new_id_holder["id"]
    audit = manager.in_memory_orders[new_id].get("follow_up_audit")
    assert audit is not None, "follow_up_audit must be set on the new order"
    assert audit["parent_stealth_order_id"] == filled_child_id
    assert audit["anchor_price"] == 50_000.0
    assert audit["posted_price"] < 50_000.0  # BUY retreated below anchor
    assert audit["retreat_applied"] is True
    assert audit["retreat_distance"] == 0.005
    assert audit["retreat_jitter"] == 0.0
    assert audit["jitter_seed"] == new_id  # seed == coid, audit-replayable


@pytest.mark.regression
def test_follow_up_audit_records_no_op_when_retreat_disabled():
    """Audit MUST be populated even when retreat was a no-op so
    consumers don't have to disambiguate 'missing field' vs 'no
    retreat applied'."""
    manager = StealthOrderManager(db_client=None)
    manager.in_memory_orders["filled-child"] = {
        "stealth_order_id": "filled-child",
        "product_id": "BIP-20DEC30-CDE",
        "side": "SELL",
        "total_size": 1.0,
        "limit_price": 50_000.0,
        "reveal_condition_json": {"type": "time_delay", "delay_seconds": 0},
        "sizing_strategy_json": {"type": "fixed"},
        "reveal_pricing_policy": "configured_limit",
        "follow_up_reveal_direction": "opposite",
        "parent_order_id": "root-aaa",
        "anchor_repricing_policy_json": {"enabled": False},
    }
    new_id_holder = {}
    def fake_create(**kwargs):
        nid = kwargs["stealth_order_id"]
        new_id_holder["id"] = nid
        manager.in_memory_orders[nid] = {
            "stealth_order_id": nid,
            "limit_price": kwargs["limit_price"],
        }
        return nid
    manager.create_stealth_order = fake_create

    manager.create_follow_up_stealth_order(
        original_stealth_order_id="filled-child",
        side="BUY",
        total_size=1.0,
        limit_price=50_000.0,
    )

    new_id = new_id_holder["id"]
    audit = manager.in_memory_orders[new_id].get("follow_up_audit")
    assert audit is not None
    assert audit["retreat_applied"] is False
    assert audit["anchor_price"] == audit["posted_price"] == 50_000.0


@pytest.mark.regression
def test_ui_field_names_match_policy_field_names():
    """Producer/consumer guard: the UI input IDs that buildAnchorRepricingPolicy
    reads must match the Python-side dataclass field names. If anyone
    renames either side without the other, this guard trips."""
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[2]
    html = (repo_root / "ui_stealth_orders_manager.html").read_text(encoding="utf-8")

    # The buildAnchorRepricingPolicy block must reference both new fields
    # by their Python-side name AND read from the matching HTML id.
    for field in ("follow_up_retreat_distance", "follow_up_retreat_jitter"):
        # Python-side key in the JSON object
        assert f"{field}:" in html, (
            f"buildAnchorRepricingPolicy must emit the {field!r} key so the "
            f"backend's RepricingPolicy normalizer can pick it up."
        )
        # Matching HTML id (anchor_<field>) the JS reads from
        assert f"id=\"anchor_{field}\"" in html, (
            f"UI must expose an input with id='anchor_{field}' so operators "
            f"can configure {field!r}."
        )
