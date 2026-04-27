"""Periodic background reconciliation auditor.

Runs :func:`core.startup_reconciler.run_startup_reconciliation` on a
fixed cadence while the engine is up, providing a continuous "deep
audit" against exchange truth that complements the WS-driven live
state and the at-startup reconciliation pass.

Industry standard for trading engines: never trust live deltas alone.
A low-frequency REST audit (5–30 minute cadence) catches:

  * Silent WS deltas dropped between reconnect snapshots
  * Drift introduced by external order placements (other clients)
  * Delayed exchange-side state transitions

Read-only by default. The auditor never mutates DB or exchange state on
its own; ``auto_heal`` follows the same opt-in semantics as the startup
reconciler so the first deployment in any environment is observe-only.

Lifecycle integration
---------------------
This module is a stop-hookable subsystem:

* ``PeriodicReconciler.start()`` spins up a daemon thread.
* ``PeriodicReconciler.stop()`` is registered via
  ``RuntimeController.register_stop_hook`` so a graceful drain joins
  it cleanly.
* The loop uses ``threading.Event.wait`` for inter-iteration sleeps so
  shutdown wakes it immediately rather than after the next interval
  expires (same pattern as the OrderEngine periodic loops).
"""

from __future__ import annotations

import threading
from datetime import timedelta
from typing import Optional

from core.startup_reconciler import run_startup_reconciliation
from logging_service import get_logger


logger = get_logger("PeriodicReconciler")


# Default cadence chosen to be:
#   * Long enough that REST rate-limit budget is irrelevant.
#   * Short enough that drift surfaces within one trading-decision cycle.
DEFAULT_INTERVAL_SECONDS = 15 * 60  # 15 minutes


class PeriodicReconciler:
    """Background thread that periodically diff-audits the engine vs exchange.

    Attributes:
        interval_seconds: Cadence between audits.
        auto_heal: Whether each audit should apply :func:`apply_auto_heal`
            to the safe drift bucket. Defaults to False (observe-only).
        audit_fills: Whether each audit should additionally invoke
            :func:`audit_missed_fills`. Defaults to False.
        fills_lookback: Override for the fills-audit lookback window
            (only consulted when ``audit_fills`` is True).
    """

    def __init__(
        self,
        *,
        interval_seconds: int = DEFAULT_INTERVAL_SECONDS,
        auto_heal: bool = False,
        audit_fills: bool = False,
        fills_lookback: Optional[timedelta] = None,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError(
                f"interval_seconds must be positive, got {interval_seconds}"
            )
        self.interval_seconds = interval_seconds
        self.auto_heal = auto_heal
        self.audit_fills = audit_fills
        self.fills_lookback = fills_lookback

        self._shutdown_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._iterations = 0  # exposed for tests / status endpoints

    @property
    def iterations(self) -> int:
        """Number of audit passes completed since ``start()``."""
        return self._iterations

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        """Start the audit thread. Idempotent."""
        if self.is_running:
            logger.info("PeriodicReconciler.start() ignored: already running")
            return
        self._shutdown_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name="PeriodicReconciler",
        )
        self._thread.start()
        logger.info(
            "PeriodicReconciler started",
            extra={
                "interval_seconds": self.interval_seconds,
                "auto_heal": self.auto_heal,
                "audit_fills": self.audit_fills,
            },
        )

    def stop(self) -> None:
        """Signal the audit thread to exit. Idempotent.

        Returns immediately. The thread will exit on its next
        ``Event.wait`` boundary (which is interrupted by ``set()``).
        Designed to be registered as a runtime-controller stop hook.
        """
        self._shutdown_event.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            # Best-effort join; we don't block the drain on a hung audit.
            thread.join(timeout=5.0)
        logger.info("PeriodicReconciler stopped")

    def _run(self) -> None:
        # Wait one full interval before the first audit so we don't
        # overlap with the at-startup reconciliation pass that main.py
        # has just run.
        if self._shutdown_event.wait(timeout=self.interval_seconds):
            return
        while not self._shutdown_event.is_set():
            self._iterations += 1
            try:
                run_startup_reconciliation(
                    fail_on_drift=False,
                    auto_heal=self.auto_heal,
                    audit_fills=self.audit_fills,
                    fills_lookback=self.fills_lookback,
                )
            except Exception:
                logger.exception(
                    "Periodic reconciliation iteration raised; continuing",
                    extra={"iteration": self._iterations},
                )
            if self._shutdown_event.wait(timeout=self.interval_seconds):
                return
