"""Reveal sizing strategies for stealth orders.

Each strategy answers ONE question: "Given the current state of this
stealth order, how big should the NEXT slice posted to the exchange be?"

Returning ``0`` means "do not post anything right now". This is the
strategy's mechanism for pacing (e.g. iceberg-style one-slice-at-a-time).

Strategies are pure: same inputs always produce the same output. Side
effects (REST cancels, audit writes, lifecycle events) live in
``StealthOrderManager``.

Architecture rationale (2026-05-03)
====================================

Extracted from ``StealthOrderManager._calculate_reveal_size`` to validate
whether the "configurable engine" goal (stop adding new code, add new
policies instead) is feasible. If three distinct sizing behaviours
(``fixed``, ``adaptive``, ``tranche-iceberg``) fit one small interface,
the abstraction holds; if not, this entire file is one-day cheap to
throw away. Nothing else depends on the interface yet.

Strategy mirrors the established
``business.stealth_condition_evaluator.ConditionEvaluator`` pattern
(ABC + concrete subclasses + factory) so it slots into the existing
mental model.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, Optional


class RevealStrategy(ABC):
    """Decides the size of the next slice to reveal.

    Strategies are stateless w.r.t. the order — all per-order state lives
    on the order dict. This rules out cross-order leakage and makes the
    strategy trivially testable in isolation.
    """

    @abstractmethod
    def compute_next_reveal_slice_size(self, order: Dict[str, Any]) -> float:
        """Return size of the next slice to post, or 0.0 to post nothing now."""

    def next_slice_size(self, order: Dict[str, Any]) -> float:
        """Backward-compatible alias for older callers."""
        compute = getattr(self, "compute_next_reveal_slice_size")
        return compute(order)


class FixedRevealStrategy(RevealStrategy):
    """Reveal the entire order in a single placement.

    Posts ``total_size`` once; subsequent calls return 0 because no
    remaining size exists. Iceberg pacing N/A — there is only ever one
    slice to consider.
    """

    def compute_next_reveal_slice_size(self, order: Dict[str, Any]) -> float:
        if float(order.get("revealed_size", 0) or 0) > 0:
            return 0.0
        return float(order.get("total_size", 0) or 0)


class AdaptiveRevealStrategy(RevealStrategy):
    """Reveal proportional to recent market volume.

    Note: does NOT include iceberg pacing in this iteration. Adaptive
    sizing is volume-driven, not fill-driven; combining both is a
    future composition (out of scope for the 2026-05-03 extraction).
    """

    def __init__(
        self,
        config: Dict[str, Any],
        market_volume_provider: Callable[[str, int], float],
        baseline_volume_provider: Callable[[str], float],
    ):
        self._config = config or {}
        self._market_volume = market_volume_provider
        self._baseline_volume = baseline_volume_provider

    def compute_next_reveal_slice_size(self, order: Dict[str, Any]) -> float:
        cfg = self._config
        total_size = float(order.get("total_size", 0) or 0)
        remaining = float(order.get("remaining_size", 0) or 0)
        if total_size <= 0 or remaining <= 0:
            return 0.0

        base_size = float(cfg.get("base_size", total_size))
        volume_window = int(cfg.get("volume_window", 60))
        reveal_multiplier = float(cfg.get("reveal_multiplier", 0.1))
        max_reveal_pct = float(cfg.get("max_reveal_percentage", 0.5))

        market_volume = self._market_volume(order["product_id"], volume_window)
        baseline_volume = self._baseline_volume(order["product_id"])
        volume_ratio = (
            market_volume / baseline_volume if baseline_volume > 0 else 1.0
        )

        reveal_size = base_size * volume_ratio * reveal_multiplier
        reveal_size = min(reveal_size, total_size * max_reveal_pct)
        reveal_size = min(reveal_size, remaining)
        return max(0.0, reveal_size)


class TrancheRevealStrategy(RevealStrategy):
    """Cumulative tranche schedule with fill-driven advance (iceberg).

    Configuration::

        {
            "type": "tranche",
            "tranches": [0.25, 0.50, 0.75, 1.0],
            "iceberg_mode": True,            # default True
        }

    Tranches are CUMULATIVE percentages of ``total_size``. With
    ``[0.25, 0.50, 0.75, 1.0]`` and total=10, the cumulative targets
    are ``[2.5, 5.0, 7.5, 10.0]``.

    Iceberg semantics (default, ``iceberg_mode=True``)
    --------------------------------------------------
    - At most ONE slice live on the exchange at any moment, gated on
      ``anchor_repricing_state_json.active_placement_client_order_id``
      (the same SSOT the reprice flow uses — no parallel tracking).
    - Next slice posts only after the previous one fills (or is
      externally cancelled, clearing the active pointer).
    - Partial fills count CUMULATIVELY against the schedule. If a
      slice posts 2.5 but only 1.8 fills before being cancelled
      externally (user / repricing), the next slice will be sized to
      bring the executed total back up to the current cumulative
      target (here: 2.5 - 1.8 = 0.7).
    - There is NO automatic cancel/timeout. Slices wait indefinitely
      for fills. Operator chose this: a never-filled slice is
      explicitly preferred over auto-chasing.

    Burst semantics (``iceberg_mode=False``, opt-out)
    -------------------------------------------------
    - All tranches post in rapid succession (matches pre-2026-05-03
      behaviour). Provided for backward compatibility with any
      operators who genuinely want N visible orders at once. This is
      anti-stealth in most contexts and is NOT recommended.

    Background (2026-05-03 incident)
    --------------------------------
    The original tranche strategy had no pacing. Combined with the
    ``should_trigger_reveal`` snapshot-commit fix, the bridge would
    call ``reveal_order_slice`` on every 100ms tick after TRIGGERED,
    posting all 4 tranches in ~1 second — defeating the entire point
    of slicing. Iceberg mode is the fix; default ``True`` because the
    burst behaviour is a bug, not a feature.
    """

    def __init__(self, config: Dict[str, Any]):
        cfg = config or {}
        self._tranches = list(cfg.get("tranches", [0.25, 0.50, 0.75, 1.0]))
        # Default True: burst behaviour is anti-stealth. See incident note.
        self._iceberg_mode = bool(cfg.get("iceberg_mode", True))

    def compute_next_reveal_slice_size(self, order: Dict[str, Any]) -> float:
        total_size = float(order.get("total_size", 0) or 0)
        if total_size <= 0:
            return 0.0

        if self._iceberg_mode:
            # Lock: a live placement exists → wait for it to settle
            # (fill or external cancel) before posting the next slice.
            if self._has_active_placement(order):
                return 0.0
            # Cumulative gating against EXECUTED size means a posted-
            # but-then-cancelled slice with partial fill rolls forward
            # to fill the gap, not to advance to the next tranche
            # (option (a) cumulative semantics from the 2026-05-03
            # design review).
            progress = float(order.get("executed_size", 0) or 0)
        else:
            # Burst mode: gate on REVEALED size to avoid posting the
            # same tranche twice on consecutive bridge ticks. This
            # preserves pre-2026-05-03 behaviour exactly.
            progress = float(order.get("revealed_size", 0) or 0)

        next_target = self._next_cumulative_target(total_size, progress)
        if next_target is None:
            return 0.0  # All cumulative targets already covered.

        slice_size = next_target - progress

        # Defensive cap against ``remaining_size`` so a misconfigured
        # tranches list ending above 1.0 cannot oversize a slice.
        revealed_size = float(order.get("revealed_size", 0) or 0)
        remaining = max(0.0, total_size - revealed_size)
        return max(0.0, min(slice_size, remaining))

    def _next_cumulative_target(
        self, total_size: float, progress: float
    ) -> Optional[float]:
        """First cumulative target above ``progress`` (or None if all met)."""
        for pct in self._tranches:
            target = total_size * float(pct)
            # 1e-9 tolerance for float math.
            if progress + 1e-9 < target:
                return target
        return None

    @staticmethod
    def _has_active_placement(order: Dict[str, Any]) -> bool:
        """True iff this stealth has a live exchange placement tracked.

        Reads the same SSOT used by the anchor reprice flow so iceberg
        and reprice cannot race on conflicting "is there a live order?"
        answers.
        """
        state = order.get("anchor_repricing_state_json") or {}
        return bool(state.get("active_placement_client_order_id"))


def get_reveal_strategy(
    strategy_type: Optional[str],
    config: Dict[str, Any],
    *,
    market_volume_provider: Optional[Callable[[str, int], float]] = None,
    baseline_volume_provider: Optional[Callable[[str], float]] = None,
) -> RevealStrategy:
    """Factory: return the strategy implementation for ``strategy_type``.

    Unknown / missing types fall back to ``FixedRevealStrategy`` to match
    the pre-extraction default branch in ``_calculate_reveal_size``.
    """
    t = (strategy_type or "fixed").lower()
    if t == "fixed":
        return FixedRevealStrategy()
    if t == "adaptive":
        if market_volume_provider is None or baseline_volume_provider is None:
            raise ValueError(
                "AdaptiveRevealStrategy requires market_volume_provider "
                "and baseline_volume_provider"
            )
        return AdaptiveRevealStrategy(
            config, market_volume_provider, baseline_volume_provider
        )
    if t == "tranche":
        return TrancheRevealStrategy(config)
    return FixedRevealStrategy()


def compute_reveal_strategy_slice_size(
    strategy: RevealStrategy,
    order: Dict[str, Any],
) -> float:
    """Single dispatch point for reveal strategy sizing."""
    compute = getattr(strategy, "compute_next_reveal_slice_size")
    return compute(order)
