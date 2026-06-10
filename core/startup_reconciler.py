"""Startup reconciliation between exchange truth and local database.

Industry standard for trading engines: after any restart there is an
unknown gap between the engine's last known state and reality on the
exchange. Orders may have filled, been cancelled, or been placed by
another client during the downtime. Running a reconciliation pass
before resuming order origination prevents phantom positions.

Strategy
--------
1. Fetch all OPEN orders from Coinbase via REST. This is exchange truth.
2. Snapshot what the local database believes is currently open
   (parent + child records that were neither FILLED, CANCELLED, EXPIRED,
   nor FAILED at last write).
3. Diff by ``client_order_id`` (canonical internal identifier).
4. Log every drift case with structured context.
5. Optionally apply conservative auto-healing for the safest drift case
   (local-shows-OPEN but exchange does not). See
   :func:`apply_auto_heal` for what is and is not healed automatically.

Usage
-----
Call :func:`run_startup_reconciliation` from ``main.py`` *before*
starting background threads and *before* setting the engine state to
RUNNING for the first time. Pass ``auto_heal=True`` to apply the safe
healing actions in the same call, or call :func:`apply_auto_heal`
manually after operator review.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set

from core.enums import EventSourceChannel, EventStreamType
from logging_service import get_logger


logger = get_logger("StartupReconciler")


# Local statuses that indicate the order is no longer open. Anything
# outside this set is treated as "engine believes it is open".
# ``RECONCILED_CLOSED`` is included because once a row has been auto-healed
# it must not be re-discovered as drift on the next reconciliation cycle.
_TERMINAL_LOCAL_STATUSES = frozenset({
    "FILLED",
    "CANCELLED",
    "EXPIRED",
    "FAILED",
    "RECONCILED_CLOSED",
})

# Pre-reveal stealth-order statuses: the row exists locally but has
# NOT been placed on the exchange yet (HIDDEN = just created;
# PENDING = condition partially met; TRIGGERED = about to place but
# not yet placed). These must be excluded from "open on exchange"
# comparisons or every hidden stealth order is reported as drift.
# Source: ``StealthOrderStatus`` in :mod:`core.enums`.
_PRE_REVEAL_LOCAL_STATUSES = frozenset({
    "HIDDEN",
    "PENDING",
    "TRIGGERED",
})

# Combined set of statuses that mean "do not compare against the
# exchange's open-orders list" — either already terminal or not yet
# placed.
_NON_EXCHANGE_OPEN_STATUSES = (
    _TERMINAL_LOCAL_STATUSES | _PRE_REVEAL_LOCAL_STATUSES
)

# Marker status applied by auto-healing. Distinct from a user-initiated
# "CANCELLED" so audit queries can identify rows that were repaired by
# startup reconciliation rather than by a normal cancel flow.
HEAL_STATUS_RECONCILED_CLOSED = "RECONCILED_CLOSED"

# Default lookback for the missed-fills audit when no explicit ``since``
# is provided. 24 hours is long enough to cover an overnight outage but
# short enough to avoid scanning the entire fill history on every restart.
DEFAULT_MISSED_FILLS_LOOKBACK = timedelta(hours=24)

# Page size matches Coinbase's documented maximum so audits complete in
# the minimum number of REST round-trips.
_FILLS_PAGE_SIZE = 100

# Hard ceiling on pagination loops to prevent runaway audits if the API
# returns ``has_next=True`` indefinitely (defensive only).
_FILLS_MAX_PAGES = 200


@dataclass
class HealResult:
    """Outcome of an :func:`apply_auto_heal` invocation."""

    healed_parent_ids: List[str] = field(default_factory=list)
    failed_ids: List[str] = field(default_factory=list)
    skipped_unknown: List[str] = field(default_factory=list)
    skipped_open_on_exchange_terminal_locally: List[str] = field(default_factory=list)

    @property
    def total_healed(self) -> int:
        return len(self.healed_parent_ids)

    def to_auto_heal_summary_dict(self) -> Dict[str, Any]:
        return {
            "healed_parents": len(self.healed_parent_ids),
            "failed": len(self.failed_ids),
            "skipped_unknown_to_local": len(self.skipped_unknown),
            "skipped_open_on_exchange_terminal_locally": len(
                self.skipped_open_on_exchange_terminal_locally
            ),
            "total_healed": self.total_healed,
        }

    def summary(self) -> Dict[str, Any]:
        return self.to_auto_heal_summary_dict()


@dataclass
class ReconciliationReport:
    """Structured outcome of a reconciliation pass.

    All ``client_order_id`` lists are canonical internal identifiers
    (per project rule P2 #7 / ORDER_ID_HANDLING.md).
    """

    exchange_open_count: int = 0
    local_open_count: int = 0

    # Open on exchange but local DB has no record at all. Could be an
    # order placed by another client, or a record we lost. Investigate.
    unknown_to_local: List[str] = field(default_factory=list)

    # Open on exchange but local DB marked it terminal. Engine state
    # drifted; local must be revived (or the exchange order cancelled).
    open_on_exchange_terminal_locally: List[str] = field(default_factory=list)

    # Open locally but exchange no longer shows it. Most common drift:
    # the order filled or was cancelled while the engine was down.
    # Local should be marked terminal once the actual outcome is known
    # (a separate reconciler queries fills history).
    closed_on_exchange_open_locally: List[str] = field(default_factory=list)

    # Both sides agree the order is open. No action required.
    in_sync: List[str] = field(default_factory=list)

    @property
    def has_drift(self) -> bool:
        return bool(
            self.unknown_to_local
            or self.open_on_exchange_terminal_locally
            or self.closed_on_exchange_open_locally
        )

    def to_startup_reconciliation_summary_dict(self) -> Dict[str, Any]:
        return {
            "exchange_open_count": self.exchange_open_count,
            "local_open_count": self.local_open_count,
            "in_sync_count": len(self.in_sync),
            "unknown_to_local_count": len(self.unknown_to_local),
            "open_on_exchange_terminal_locally_count": len(
                self.open_on_exchange_terminal_locally
            ),
            "closed_on_exchange_open_locally_count": len(
                self.closed_on_exchange_open_locally
            ),
            "has_drift": self.has_drift,
        }

    def summary(self) -> Dict[str, Any]:
        return self.to_startup_reconciliation_summary_dict()


def _fetch_exchange_open_client_order_ids() -> Set[str]:
    """Return the set of ``client_order_id`` values currently OPEN on Coinbase.

    Uses ``REST_CLIENT.list_orders`` which is the same code path used
    elsewhere in the engine, so reconciliation reflects what the
    production code sees.
    """
    from configuration import REST_CLIENT  # late import to avoid cycles
    from external.coinbase_client import coinbase_sdk_response_to_dict

    response = REST_CLIENT.list_orders(order_status=["OPEN"])
    raw = coinbase_sdk_response_to_dict(response)
    orders = raw.get("orders", []) if isinstance(raw, dict) else []
    ids: Set[str] = set()
    for order in orders:
        coid = order.get("client_order_id")
        if coid:
            ids.add(coid)
    return ids


def _fetch_local_open_client_order_ids() -> Set[str]:
    """Return ``client_order_id`` values the local DB believes are open.

    Pulls from ``order_parent`` (the flat hierarchy table that holds
    both parent and child orders), filtering out any record whose
    status is in :data:`_NON_EXCHANGE_OPEN_STATUSES` — that is, either
    already terminal (FILLED/CANCELLED/...) or pre-reveal stealth
    (HIDDEN/PENDING/TRIGGERED). Pre-reveal rows do not exist on the
    exchange by design, so including them would falsely report every
    hidden stealth order as drift.

    Records with no status (legacy rows) are treated conservatively
    as open so they show up for inspection rather than being silently
    dropped.
    """
    from database.database import PostgresDB

    db = PostgresDB()
    try:
        ids: Set[str] = set()
        try:
            rows = db.execute_query(
                "SELECT client_order_id, status FROM order_parent"
            )
        except Exception:
            # Table may not exist in dev environments; log and skip.
            logger.exception(
                "Reconciliation: failed to read from order_parent, skipping"
            )
            return ids
        for row in rows or ():
            coid = row.get("client_order_id") if isinstance(row, dict) else None
            status = row.get("status") if isinstance(row, dict) else None
            if not coid:
                continue
            if status and str(status).upper() in _NON_EXCHANGE_OPEN_STATUSES:
                continue
            ids.add(coid)
        return ids
    finally:
        try:
            db.disconnect()
        except Exception:
            pass


def run_startup_reconciliation(
    *,
    fail_on_drift: bool = False,
    auto_heal: bool = False,
    audit_fills: bool = False,
    fills_lookback: Optional[timedelta] = None,
) -> Optional[ReconciliationReport]:
    """Compare exchange OPEN orders against local DB and log any drift.

    Args:
        fail_on_drift: If True, raise ``RuntimeError`` when drift is
            detected. Use in strict environments where any uncertainty
            about exchange state should block engine startup. Default
            False (log + continue), matching how production trading
            engines typically behave: drift is expected after any
            restart and operators want the engine running so they can
            inspect and resolve.
        auto_heal: If True, immediately invoke :func:`apply_auto_heal`
            for the safest drift bucket (local-OPEN /
            exchange-not-OPEN) after logging the report. The heal
            outcome is logged separately. Default False so the first
            run after every restart is observe-only.
        audit_fills: If True, additionally invoke
            :func:`audit_missed_fills` to detect fills the WS pipeline
            missed during downtime. The audit result is logged but the
            fill_ledger is NOT mutated; operators decide whether to
            replay missed fills via the existing FillReconciler. Default
            False so dev environments without live API access still
            start cleanly.
        fills_lookback: Override the default 24-hour lookback window
            used by the fills audit. Ignored when ``audit_fills`` is
            False.

    Returns:
        :class:`ReconciliationReport` when reconciliation completed (with
        or without drift), or ``None`` if it could not be performed
        (e.g. REST client unavailable). A ``None`` return is logged as
        a warning but is non-fatal so local dev environments without
        live API credentials can still start up.
    """
    logger.info("Startup reconciliation: starting (REST OPEN vs local DB)")

    try:
        exchange_ids = _fetch_exchange_open_client_order_ids()
    except Exception:
        logger.exception(
            "Startup reconciliation skipped: could not fetch open orders "
            "from REST. Engine will start without verifying exchange state."
        )
        return None

    try:
        local_ids = _fetch_local_open_client_order_ids()
    except Exception:
        logger.exception("Startup reconciliation skipped: local DB read failed")
        return None

    # For the "open on exchange but terminal locally" bucket we also need
    # the local rows that *do* exist but in terminal state, so we can
    # distinguish "unknown" (no row at all) from "stale" (terminal row).
    try:
        from database.database import PostgresDB
        db = PostgresDB()
        all_local_ids: Set[str] = set()
        try:
            try:
                rows = db.execute_query(
                    "SELECT client_order_id FROM order_parent"
                )
            except Exception:
                rows = []
            for row in rows or ():
                coid = row.get("client_order_id") if isinstance(row, dict) else None
                if coid:
                    all_local_ids.add(coid)
        finally:
            try:
                db.disconnect()
            except Exception:
                pass
    except Exception:
        logger.exception("Startup reconciliation: failed enumerating local IDs")
        all_local_ids = local_ids  # safe fallback

    report = ReconciliationReport(
        exchange_open_count=len(exchange_ids),
        local_open_count=len(local_ids),
    )

    for coid in exchange_ids:
        if coid in local_ids:
            report.in_sync.append(coid)
        elif coid in all_local_ids:
            report.open_on_exchange_terminal_locally.append(coid)
        else:
            report.unknown_to_local.append(coid)

    for coid in local_ids:
        if coid not in exchange_ids:
            report.closed_on_exchange_open_locally.append(coid)

    summary = report.to_startup_reconciliation_summary_dict()
    if report.has_drift:
        logger.warning(
            "Startup reconciliation: drift detected. Inspect the report "
            "before placing new orders.",
            extra={"reconciliation_summary": summary},
        )
        for coid in report.unknown_to_local:
            logger.warning(
                f"Drift: exchange has OPEN order with no local record "
                f"client_order_id={coid}",
                extra={"client_order_id": coid},
            )
        for coid in report.open_on_exchange_terminal_locally:
            logger.warning(
                f"Drift: exchange shows OPEN but local DB marked terminal "
                f"client_order_id={coid}",
                extra={"client_order_id": coid},
            )
        for coid in report.closed_on_exchange_open_locally:
            logger.warning(
                f"Drift: local DB shows OPEN but exchange has no OPEN record "
                f"client_order_id={coid}",
                extra={"client_order_id": coid},
            )
        if fail_on_drift:
            raise RuntimeError(
                f"Startup reconciliation drift: {summary}. "
                f"Set fail_on_drift=False to start despite drift."
            )
    else:
        logger.info(
            "Startup reconciliation: clean (no drift between exchange and DB)",
            extra={"reconciliation_summary": summary},
        )

    if auto_heal and report.has_drift:
        heal_result = apply_auto_heal(report)
        logger.info(
            "Startup reconciliation: auto-heal completed",
            extra={"auto_heal_summary": heal_result.to_auto_heal_summary_dict()},
        )

    if audit_fills:
        try:
            since = (
                datetime.now(timezone.utc) - fills_lookback
                if fills_lookback is not None
                else None
            )
            audit_missed_fills(since=since)
        except Exception:
            logger.exception("Missed-fills audit raised; continuing")

    return report


def apply_auto_heal(report: ReconciliationReport) -> HealResult:
    """Apply conservative auto-healing for the safest drift bucket.

    Healed automatically:
      * ``closed_on_exchange_open_locally`` — local DB marks the order
        as OPEN (or non-terminal) but the exchange has no record of it
        being open. We mark these locally with status
        :data:`HEAL_STATUS_RECONCILED_CLOSED` so they stop being
        considered for fills / replacements / spread, while leaving an
        audit trail distinct from a normal user cancellation.

    NOT healed automatically (logged for operator review only):
      * ``unknown_to_local`` — exchange shows an OPEN order with no
        local record. This is risky to auto-resolve: it could be a
        legitimate order from another client, a record we lost, or an
        order placed by an earlier version of the engine. Operator
        decides.
      * ``open_on_exchange_terminal_locally`` — exchange shows OPEN
        but our local copy is terminal. We will not silently revive
        terminal records; manual investigation is required to decide
        whether to re-open the local row or cancel on the exchange.

    The healing writes use the same database connection / SQL path as
    the rest of the engine (no parallel persistence layer) and are
    idempotent — re-running on already-healed rows is safe (the UPDATE
    matches zero rows because they no longer satisfy the
    "non-terminal" precondition).

    Args:
        report: The :class:`ReconciliationReport` returned by
            :func:`run_startup_reconciliation`.

    Returns:
        :class:`HealResult` summarizing what was healed and what was
        skipped. Per-id failures are reported in ``failed_ids`` and
        logged but never raise — startup must remain robust.
    """
    from database.database import PostgresDB

    result = HealResult(
        skipped_unknown=list(report.unknown_to_local),
        skipped_open_on_exchange_terminal_locally=list(
            report.open_on_exchange_terminal_locally
        ),
    )

    if not report.closed_on_exchange_open_locally:
        return result

    db = PostgresDB()
    try:
        # UPDATE is gated on the row currently being non-terminal so a
        # concurrent terminal write (e.g. fill processed during
        # reconciliation) wins over us. The flat hierarchy means both
        # parents and children live in order_parent, so a single pass
        # heals every safe drift.
        terminal_list = ",".join("%s" for _ in _TERMINAL_LOCAL_STATUSES)
        terminal_params = tuple(_TERMINAL_LOCAL_STATUSES)
        for coid in report.closed_on_exchange_open_locally:
            try:
                parent_rows = db.execute_update(
                    f"UPDATE order_parent SET status = %s "
                    f"WHERE client_order_id = %s "
                    f"AND (status IS NULL OR status NOT IN ({terminal_list}))",
                    (HEAL_STATUS_RECONCILED_CLOSED, coid, *terminal_params),
                )
            except Exception:
                logger.exception(
                    "Auto-heal: order_parent update failed",
                    extra={"client_order_id": coid},
                )
                result.failed_ids.append(coid)
                continue

            if parent_rows:
                result.healed_parent_ids.append(coid)
                logger.info(
                    "Auto-heal: marked order_parent record RECONCILED_CLOSED",
                    extra={"client_order_id": coid},
                )
    finally:
        try:
            db.disconnect()
        except Exception:
            pass

    return result


# ---------------------------------------------------------------------------
# Missed-fills audit (REST historical/fills vs local fill_ledger)
# ---------------------------------------------------------------------------


@dataclass
class MissedFillsReport:
    """Outcome of an :func:`audit_missed_fills` invocation.

    Attributes:
        scanned_since: ISO timestamp of the lower bound passed to
            ``REST_CLIENT.list_fills``.
        scanned_until: ISO timestamp of the upper bound (or ``None`` for "now").
        rest_fills_examined: Total fills returned by the REST API across all
            pages.
        already_recorded: Fills whose ``entry_id`` is already present in the
            local ``fill_ledger`` (no action required).
        missed: Fills with no matching ``fill_ledger`` row — the WebSocket
            pipeline did not record them. Each entry is the raw REST fill
            dict so operators have full context for forensic review.
        failed_pages: Pages whose REST fetch raised an exception (audit is
            best-effort).
    """

    scanned_since: Optional[str] = None
    scanned_until: Optional[str] = None
    rest_fills_examined: int = 0
    already_recorded: int = 0
    missed: List[Dict[str, Any]] = field(default_factory=list)
    failed_pages: int = 0

    @property
    def has_missed_fills(self) -> bool:
        return bool(self.missed)

    def to_missed_fills_summary_dict(self) -> Dict[str, Any]:
        return {
            "scanned_since": self.scanned_since,
            "scanned_until": self.scanned_until,
            "rest_fills_examined": self.rest_fills_examined,
            "already_recorded": self.already_recorded,
            "missed_count": len(self.missed),
            "failed_pages": self.failed_pages,
        }

    def summary(self) -> Dict[str, Any]:
        return self.to_missed_fills_summary_dict()


def _fetch_local_recorded_entry_ids() -> Set[str]:
    """Return the set of ``exchange_entry_id`` values currently in fill_ledger.

    Used to diff against the REST fills page-by-page. Pulled in one query
    because the index size (one UUID per fill) is small even at high
    fill volume; pagination would only matter at multi-million-fill scale.
    """
    from database.database import PostgresDB

    db = PostgresDB()
    try:
        try:
            rows = db.execute_query(
                "SELECT exchange_entry_id FROM fill_ledger "
                "WHERE exchange_entry_id IS NOT NULL"
            )
        except Exception:
            logger.exception(
                "Missed-fills audit: failed to read fill_ledger; "
                "treating local set as empty (will over-report missed fills)"
            )
            return set()
        return {
            row.get("exchange_entry_id")
            for row in rows or ()
            if isinstance(row, dict) and row.get("exchange_entry_id")
        }
    finally:
        try:
            db.disconnect()
        except Exception:
            pass


# Quantity tolerance when summing WS_DERIVED rows against REST per-order
# totals. WS rows store size at 8-decimal precision; one ULP is plenty.
_WS_PENDING_QTY_TOLERANCE = 1e-6


def _fetch_ws_pending_qty_by_client_order_id() -> Dict[str, float]:
    """Sum WS_DERIVED quantity per ``client_order_id`` in fill_ledger.

    These are rows the WebSocket pipeline persisted but that have not yet
    been paired with their REST counterpart (so ``exchange_entry_id`` is
    NULL). They are NOT missed — they are pending REST reconciliation.
    The audit must treat them as "already recorded" or it re-reports
    every recent live fill until ``FillReconciler`` runs.
    """
    from database.database import PostgresDB

    db = PostgresDB()
    try:
        try:
            rows = db.execute_query(
                "SELECT client_order_id, SUM(quantity) AS total_qty FROM fill_ledger WHERE reconciliation_status = 'WS_DERIVED' AND exchange_entry_id IS NULL AND client_order_id IS NOT NULL GROUP BY client_order_id"
            )
        except Exception:
            logger.exception(
                "Missed-fills audit: failed to read WS_DERIVED rows; "
                "will over-report missed fills for live orders"
            )
            return {}
        result: Dict[str, float] = {}
        for row in rows or ():
            if not isinstance(row, dict):
                continue
            coid = row.get("client_order_id")
            qty = row.get("total_qty")
            if not coid or qty is None:
                continue
            try:
                result[coid] = float(qty)
            except (TypeError, ValueError):
                continue
        return result
    finally:
        try:
            db.disconnect()
        except Exception:
            pass


def _fetch_client_order_ids_for_exchange_order_ids(
    exchange_order_ids: Set[str],
) -> Dict[str, str]:
    """Resolve exchange ``order_id`` -> internal ``client_order_id``.

    Source of truth is owned submission evidence in ``order_event_stream``.
    Observed exchange events can include shared-account orders, so ownership
    requires the local REST submission record.
    """
    if not exchange_order_ids:
        return {}
    from database.database import PostgresDB

    db = PostgresDB()
    try:
        placeholders = ",".join("%s" for _ in exchange_order_ids)
        try:
            rows = db.execute_query(
                (
                    "SELECT order_id, client_order_id FROM order_event_stream "
                    f"WHERE order_id IN ({placeholders}) "
                    "AND client_order_id IS NOT NULL "
                    "AND event_type = %s "
                    "AND source_channel = %s "
                    "GROUP BY order_id, client_order_id"
                ),
                (
                    *tuple(exchange_order_ids),
                    EventStreamType.ORDER_SUBMITTED.value,
                    EventSourceChannel.REST_SUBMIT.value,
                ),
            )
        except Exception:
            logger.exception(
                "Missed-fills audit: failed to map exchange order_ids "
                "to client_order_ids; WS-pending suppression will be partial"
            )
            return {}
        mapping: Dict[str, str] = {}
        for row in rows or ():
            if not isinstance(row, dict):
                continue
            oid = row.get("order_id")
            coid = row.get("client_order_id")
            if oid and coid:
                mapping[oid] = coid
        return mapping
    finally:
        try:
            db.disconnect()
        except Exception:
            pass


def audit_missed_fills(
    *,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    product_id: Optional[str] = None,
) -> Optional[MissedFillsReport]:
    """Detect fills the WebSocket pipeline missed during downtime.

    Industry pattern: WS user-channel deltas drive live state, but the
    REST ``orders/historical/fills`` endpoint is the only authoritative
    per-match source. After any restart or reconnect there is a window
    during which fills can occur with no live consumer attached. This
    audit pulls every REST fill in the lookback window and flags any
    whose ``entry_id`` is not present in the local ``fill_ledger``.

    Read-only by design. The function never inserts into ``fill_ledger``
    itself: the live derived-fill path (``append_derived_fill``) owns
    that table's idempotency key (``derived_trade_key``), and silently
    backfilling REST rows would skip the lot-tracking and follow-up
    pipelines that depend on ``OrderSnapshotDelta``. Operators review
    the report and either reprocess via the existing ``FillReconciler``
    or accept the gap.

    Args:
        since: Lower bound for ``trade_time``. Defaults to
            now - :data:`DEFAULT_MISSED_FILLS_LOOKBACK`.
        until: Upper bound. ``None`` means "now" (no upper bound sent).
        product_id: Restrict to one product. ``None`` audits all
            products subscribed on the account.

    Returns:
        :class:`MissedFillsReport`, or ``None`` if the REST client is
        unavailable. Returning ``None`` is non-fatal so dev environments
        without live API credentials still start.
    """
    from configuration import REST_CLIENT  # late import to avoid cycles

    if since is None:
        since = datetime.now(timezone.utc) - DEFAULT_MISSED_FILLS_LOOKBACK
    since_iso = since.isoformat()
    until_iso = until.isoformat() if until is not None else None

    report = MissedFillsReport(
        scanned_since=since_iso,
        scanned_until=until_iso,
    )

    try:
        local_entry_ids = _fetch_local_recorded_entry_ids()
    except Exception:
        logger.exception("Missed-fills audit aborted: could not read local ledger")
        return None

    cursor: Optional[str] = None
    pages = 0
    while pages < _FILLS_MAX_PAGES:
        pages += 1
        try:
            page = REST_CLIENT.list_fills(
                start_date=since_iso,
                end_date=until_iso,
                product_id=product_id,
                cursor=cursor,
                limit=_FILLS_PAGE_SIZE,
            )
        except Exception:
            logger.exception(
                "Missed-fills audit: REST fetch failed on page",
                extra={"page": pages, "cursor": cursor},
            )
            report.failed_pages += 1
            break

        fills = page.get("fills", []) if isinstance(page, dict) else []
        for fill in fills:
            report.rest_fills_examined += 1
            entry_id = fill.get("entry_id")
            if entry_id and entry_id in local_entry_ids:
                report.already_recorded += 1
            else:
                report.missed.append(fill)

        cursor = page.get("cursor") if isinstance(page, dict) else None
        has_next = bool(page.get("has_next")) if isinstance(page, dict) else False
        if not has_next or not cursor:
            break
    else:
        # Loop exhausted the page ceiling — extremely unlikely in
        # practice; log so this never goes unnoticed.
        logger.warning(
            "Missed-fills audit: hit page ceiling; results may be partial",
            extra={"page_ceiling": _FILLS_MAX_PAGES},
        )

    # ------------------------------------------------------------------
    # Suppress false positives for WS-pending fills.
    #
    # WS-derived fill_ledger rows carry NULL exchange_entry_id until the
    # FillReconciler pairs them with the REST fill and stamps the IDs.
    # Without this step the audit reports every recent live fill as
    # "missed" because the entry_id lookup misses, even though the row
    # IS already in the ledger (just not yet stamped).
    #
    # Strategy: per exchange order_id, sum the REST qty in this report's
    # `missed` list and compare against the WS_DERIVED qty for the
    # corresponding internal client_order_id. If WS already covers (or
    # exceeds) the REST total for that order, treat all of those REST
    # rows as already recorded and demote them out of `missed`.
    # ------------------------------------------------------------------
    oid_to_coid: Dict[str, str] = {}
    if report.missed:
        order_ids_in_missed = {
            str(f.get("order_id"))
            for f in report.missed
            if f.get("order_id")
        }
        oid_to_coid = _fetch_client_order_ids_for_exchange_order_ids(
            order_ids_in_missed
        )
        ws_pending_by_coid = _fetch_ws_pending_qty_by_client_order_id()

        # Sum REST qty per order_id (within the missed list).
        rest_qty_by_oid: Dict[str, float] = {}
        for f in report.missed:
            oid = str(f.get("order_id") or "")
            if not oid:
                continue
            try:
                rest_qty_by_oid[oid] = (
                    rest_qty_by_oid.get(oid, 0.0) + float(f.get("size") or 0)
                )
            except (TypeError, ValueError):
                continue

        # Decide which order_ids are fully covered by WS-pending rows.
        ws_covered_oids: Set[str] = set()
        for oid, rest_total in rest_qty_by_oid.items():
            coid = oid_to_coid.get(oid)
            if not coid:
                continue
            ws_total = ws_pending_by_coid.get(coid, 0.0)
            if ws_total + _WS_PENDING_QTY_TOLERANCE >= rest_total:
                ws_covered_oids.add(oid)

        if ws_covered_oids:
            kept: List[Dict[str, Any]] = []
            suppressed = 0
            for f in report.missed:
                if str(f.get("order_id") or "") in ws_covered_oids:
                    suppressed += 1
                else:
                    kept.append(f)
            report.missed = kept
            report.already_recorded += suppressed
            logger.info(
                "Missed-fills audit [window %s -> %s, product=%s]: "
                "suppressed %d REST row(s) across %d order(s) covered by "
                "WS_DERIVED rows pending entry_id stamp "
                "(run FillReconciler to stamp them).",
                since_iso,
                until_iso or "now",
                product_id or "<all>",
                suppressed,
                len(ws_covered_oids),
            )

    # ------------------------------------------------------------------
    # Partition by ownership.
    #
    # The audit is designed to catch "WS pipeline missed a fill for an
    # order WE placed". A fill whose exchange order_id has no row in
    # `order_event_stream` was placed by something that isn't this
    # engine instance — most often a previous engine run before the
    # local DB was created/wiped, or a manual exchange-side trade.
    # We can't backfill it (no client_order_id mapping exists) and it
    # isn't a WS gap from our perspective. Log a single INFO summary
    # for visibility and demote those rows out of `missed` so the
    # WARNING loop only fires for real gaps in orders we own.
    #
    # This also subsumes the old fresh-DB detector: a fresh DB has
    # zero `order_event_stream` rows, so every REST fill is unowned
    # and the WARNING loop is naturally silent.
    # ------------------------------------------------------------------
    if report.missed:
        # If suppression above already populated oid_to_coid, the post-
        # suppression `missed` list is a strict subset and that mapping
        # is still authoritative. Otherwise resolve now.
        if not oid_to_coid:
            oid_to_coid = _fetch_client_order_ids_for_exchange_order_ids(
                {str(f.get("order_id")) for f in report.missed if f.get("order_id")}
            )

        owned: List[Dict[str, Any]] = []
        unowned: List[Dict[str, Any]] = []
        for f in report.missed:
            oid = str(f.get("order_id") or "")
            if oid and oid in oid_to_coid:
                owned.append(f)
            else:
                unowned.append(f)

        if unowned:
            logger.info(
                "Missed-fills audit [window %s -> %s, product=%s]: "
                "%d REST fill(s) across %d unowned order(s) have no "
                "order_event_stream mapping (placed by a previous engine "
                "instance, pre-wipe, or off-engine). Not backfillable; not "
                "a WS gap. Use the backfill CLI only if you can supply the "
                "original client_order_id externally.",
                since_iso,
                until_iso or "now",
                product_id or "<all>",
                len(unowned),
                len({str(f.get("order_id") or "") for f in unowned}),
                extra={
                    "unowned_order_ids": sorted(
                        {str(f.get("order_id") or "") for f in unowned}
                    ),
                },
            )

        report.missed = owned

    summary = report.to_missed_fills_summary_dict()
    if report.has_missed_fills:
        logger.warning(
            "Missed-fills audit [window %s -> %s, product=%s, "
            "rest_examined=%d, pages=%d]: detected fills not in local "
            "ledger for orders we own. WS pipeline likely had a gap; "
            "investigate before placing new orders.",
            since_iso,
            until_iso or "now",
            product_id or "<all>",
            report.rest_fills_examined,
            pages,
            extra={"missed_fills_summary": summary},
        )
        for fill in report.missed:
            logger.warning(
                "Missed fill: "
                f"product={fill.get('product_id')} "
                f"side={fill.get('side')} "
                f"size={fill.get('size')} "
                f"price={fill.get('price')} "
                f"trade_time={fill.get('trade_time')} "
                f"order_id={fill.get('order_id')} "
                f"entry_id={fill.get('entry_id')}",
                extra={
                    "entry_id": fill.get("entry_id"),
                    "trade_id": fill.get("trade_id"),
                    "order_id": fill.get("order_id"),
                    "product_id": fill.get("product_id"),
                    "side": fill.get("side"),
                    "size": fill.get("size"),
                    "price": fill.get("price"),
                    "trade_time": fill.get("trade_time"),
                },
            )
    else:
        logger.info(
            "Missed-fills audit [window %s -> %s, product=%s, "
            "rest_examined=%d, pages=%d]: clean (every REST fill is in "
            "local ledger).",
            since_iso,
            until_iso or "now",
            product_id or "<all>",
            report.rest_fills_examined,
            pages,
            extra={"missed_fills_summary": summary},
        )

    return report
