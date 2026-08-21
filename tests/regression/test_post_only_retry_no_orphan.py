"""Regression: post-only retry must not orphan the placement from
its stealth chain.

Background (2026-05-01 production incident)
============================================

The first deploy of the post-only retry loop generated a fresh COID
on every POST_ONLY rejection but left the order_parent pre-insert
OUTSIDE the retry loop. The pre-insert ran once with the original
COID; when the original COID equalled ``stealth_order_id`` (the
no-reprice policy path) the pre-insert was skipped entirely.

Result: when the retry succeeded with a new COID, the WS user-channel
handler arrived first, found no chain-linked row, and inserted the
placement as a NEW ROOT in ``order_parent`` — orphaning it from the
stealth chain root. Concretely (from production logs):

    16:07:21,895 - post_only_retry: rejected=c88c3aed, next=b4b772bb
    16:07:22,116 - parent_order_entry_created (b4b772bb)  [WS]
    16:07:22,120 - WARNING - No parent order found to update status
    16:07:22,128 - ✓ Root parent order inserted: b4b772bb (DB ID: 64)
                   ^^^^ should have been a CHILD of e30d58d8

Contract under test
====================

1. The pre-insert helper ``_pre_insert_placement_row`` exists and is
   called from inside the retry loop, not before it.
2. Each retry attempt with a fresh COID gets its own pre-insert.
3. POST_ONLY rejections mark the rejected COID's pre-inserted row
   FAILED so the audit trail reflects what happened on the exchange.
4. The success log reports the ACTUAL submitted price (post-retry),
   not the stale ``reveal_plan.submitted_limit_price``.
"""
from __future__ import annotations

from pathlib import Path

import pytest


_STEALTH_MANAGER_SRC = (
    Path(__file__).resolve().parents[2]
    / "core"
    / "stealth_order_manager.py"
).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Static-source guards
# ---------------------------------------------------------------------------


@pytest.mark.regression
def test_pre_insert_helper_exists():
    """The per-attempt pre-insert helper must exist; without it the
    retry loop can't re-link a fresh COID to the chain root."""
    assert "def _pre_insert_placement_row" in _STEALTH_MANAGER_SRC


@pytest.mark.regression
def test_pre_insert_called_from_inside_retry_loop():
    """The pre-insert must be invoked INSIDE the retry loop, before
    each REST call. A pre-insert outside the loop only covers the
    first attempt's COID and orphans every retry COID."""
    # Find the retry loop.
    loop_marker = "for attempt_num in range(1, max_attempts + 1):"
    assert loop_marker in _STEALTH_MANAGER_SRC, (
        "Retry loop marker missing — test needs updating"
    )
    loop_start = _STEALTH_MANAGER_SRC.index(loop_marker)
    # Find the next REST call after the loop start.
    rest_call_marker = "REST_CLIENT.place_limit_order("
    rest_idx = _STEALTH_MANAGER_SRC.index(rest_call_marker, loop_start)
    # The pre-insert call must appear between loop start and REST call.
    body = _STEALTH_MANAGER_SRC[loop_start:rest_idx]
    assert "_pre_insert_placement_row(attempt_coid, attempt_price)" in body, (
        "Pre-insert must run BEFORE the place_limit_order call inside "
        "the retry loop. Otherwise a retry's fresh COID has no "
        "chain-linked row when the WS handler arrives, and the "
        "placement is orphaned as a root in order_parent."
    )


@pytest.mark.regression
def test_rejected_attempt_marked_failed():
    """When a POST_ONLY rejection arrives, the pre-inserted row for
    that COID must be marked FAILED so the audit trail does not show
    a phantom PENDING row for an order that never made the exchange."""
    loop_start = _STEALTH_MANAGER_SRC.index(
        "for attempt_num in range(1, max_attempts + 1):"
    )
    loop_end = _STEALTH_MANAGER_SRC.index(
        "if classification is None or not classification.accepted:",
        loop_start,
    )
    loop_body = _STEALTH_MANAGER_SRC[loop_start:loop_end]
    assert "self._mark_placement_parent_failed(" in loop_body
    assert "attempt_coid," in loop_body


@pytest.mark.regression
def test_success_log_uses_actual_submitted_price_not_plan():
    """The placed-successfully log must report the ACTUAL submitted
    price (post-retry), not the stale plan price. Pre-fix: every
    retry-success log mis-reported the original ticker price."""
    assert "actual_submitted_price = float(order_for_submission" in _STEALTH_MANAGER_SRC
    # The stale pattern (reading directly from reveal_plan in the
    # success log) must be gone from the success log block.
    success_log_marker = '"event": "stealth_order_slice_placed_successfully"'
    assert success_log_marker in _STEALTH_MANAGER_SRC
    success_log_idx = _STEALTH_MANAGER_SRC.index(success_log_marker)
    # Look at a window around the success log.
    window = _STEALTH_MANAGER_SRC[success_log_idx:success_log_idx + 1500]
    assert '"submitted_limit_price": actual_submitted_price' in window, (
        "Success log must use actual_submitted_price (post-retry), "
        "not reveal_plan.submitted_limit_price (pre-retry)."
    )


@pytest.mark.regression
def test_pre_insert_and_rejection_status_use_the_same_attempt_coid():
    """Each retry's audit row and terminal rejection update must share
    the exact client_order_id sent to REST."""
    loop_start = _STEALTH_MANAGER_SRC.index(
        "for attempt_num in range(1, max_attempts + 1):"
    )
    loop_end = _STEALTH_MANAGER_SRC.index(
        "if classification is None or not classification.accepted:",
        loop_start,
    )
    loop_body = _STEALTH_MANAGER_SRC[loop_start:loop_end]
    assert "_pre_insert_placement_row(attempt_coid, attempt_price)" in loop_body
    assert "client_order_id=attempt_coid" in loop_body
    assert "self._mark_placement_parent_failed(\n                attempt_coid" in loop_body
