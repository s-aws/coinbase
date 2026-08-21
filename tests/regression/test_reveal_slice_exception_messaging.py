"""Regression: reveal_order_slice must distinguish REST-failure from
post-placement-bookkeeping-failure in its exception logging.

History (2026-04-29 incident, follow-up to the Order.from_dict bug)
====================================================================

Original ``reveal_order_slice`` had a single broad ``except`` block that
unconditionally logged::

    {"event": "stealth_order_slice_placement_exception",
     "note": "Exception while placing order on exchange. Order was NOT placed."}

This was *false* in the actual incident: the REST ``place_limit_order``
call had already returned successfully, the exchange already had the
order, and the exception came from a downstream ``Order.from_dict`` shim
inside the SDK wrapper. Operators reading the log saw "order was not
placed" and didn't realize a real, fillable, live order was sitting on
the exchange with no follow-up wiring.

The current fix uses the shared fail-closed response classifier. A REST return
is not accepted unless Coinbase explicitly reports success with a usable
exchange order id. The flow branches on classified acceptance:

* rejected/indeterminate -> ``stealth_order_slice_placement_failed`` and no
  success bookkeeping;
* accepted, then local finalization raised
  -> ``stealth_order_slice_local_finalization_error`` +
  "Order IS LIVE on the exchange; operator action may be required"
  (truthful "placed but linkage lost").

Static-source guards below pin both branches so a future refactor can't
silently re-introduce the misleading single-event behavior.
"""
from __future__ import annotations

from pathlib import Path

import pytest


_SRC = (
    Path(__file__).resolve().parents[2]
    / "core"
    / "stealth_order_manager.py"
).read_text(encoding="utf-8")


@pytest.mark.regression
def test_reveal_slice_classifies_acceptance_separately():
    """REST return alone must never be the success predicate."""
    assert "classify_placement_response(" in _SRC
    assert "classification.accepted" in _SRC
    assert "rest_call_succeeded" not in _SRC


@pytest.mark.regression
def test_reveal_slice_emits_distinct_events_for_two_failure_modes():
    """Two distinct event names are required so dashboards/alerting can
    treat 'order live but unlinked' as the operationally critical
    incident it is, separately from 'order failed to place'."""
    assert "stealth_order_slice_placement_failed" in _SRC, (
        "REST-failure event name missing."
    )
    assert "stealth_order_slice_local_finalization_error" in _SRC, (
        "Post-placement exception event name missing — see "
        "2026-04-29 incident."
    )


@pytest.mark.regression
def test_reveal_slice_post_placement_note_states_order_is_live():
    """The post-placement branch's operator-facing note MUST clearly
    state the order is live on the exchange. Anything weaker risks a
    repeat of the 2026-04-29 incident where the operator dismissed the
    error and missed a real fill."""
    assert "IS LIVE on the exchange" in _SRC, (
        "Post-placement exception note has been weakened. The whole "
        "point of the 2026-04-29 fix is to make it impossible to "
        "misread the log: the order IS LIVE."
    )


@pytest.mark.regression
def test_reveal_slice_does_not_use_old_misleading_note():
    """Guard against a future commit re-introducing the original
    misleading note in any branch."""
    misleading = "Exception while placing order on exchange. Order was NOT placed."
    assert misleading not in _SRC, (
        f"Old misleading note re-introduced: {misleading!r}. "
        "This wording was removed in the 2026-04-29 fix because it "
        "lies in the post-placement-exception case (the order IS on "
        "the exchange). Use the two-branch pattern."
    )
