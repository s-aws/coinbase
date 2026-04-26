"""Reconcile WS-derived fill_ledger rows against authoritative REST fills.

The live WS pipeline writes per-match rows to ``fill_ledger`` with
``reconciliation_status = 'WS_DERIVED'`` keyed by a synthetic
``derived_trade_key`` (deterministic UUID5 of
``client_order_id`` × ``cumulative_quantity``). Coinbase's REST
``GET /api/v3/brokerage/orders/historical/fills`` is the only authoritative
per-match source; this module pairs the two and stamps the ledger rows with
the real ``exchange_trade_id`` / ``exchange_entry_id``.

Design constraints (see project plan):
    * Pure logic. The REST call is injected as a ``fills_fetcher`` callable
      so this module has no SDK dependency and is fully unit-testable.
    * One transaction per order (all ledger rows for a given
      ``client_order_id`` move from WS_DERIVED to a terminal status atomically).
    * Greedy size-then-price matching is sufficient because per-match WS
      deltas should agree with REST trades within rounding tolerance; any
      structural disagreement is exactly what we need to surface.
    * Never delete rows. Mismatches are flagged for operator review.

Reconciliation outcomes per WS row:
    RECONCILED  – paired 1:1 with a REST fill (size + price within tolerance).
    MISMATCH    – present in fill_ledger but no compatible REST fill found.

REST fills with no compatible WS row are reported but not inserted; they
indicate a WS pipeline gap that warrants forensic investigation rather than
silent backfill.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple


logger = logging.getLogger(__name__)


# Type alias: a fetcher takes an exchange order id and returns the list of
# REST historical/fills row dicts for that order.
FillsFetcher = Callable[[str], List[Dict[str, Any]]]


# Size deltas are derived from cumulative_quantity counters which Coinbase
# reports at 8-decimal precision; allow one ULP of rounding error.
DEFAULT_SIZE_TOLERANCE = 1e-8
# Per-match price is value/size from WS counters; REST reports rounded price.
# 0.01% covers the worst rounding plus penny-level price granularity.
DEFAULT_PRICE_TOLERANCE_PCT = 0.0001


@dataclass(frozen=True)
class ReconcileMatch:
    """A successful 1:1 pairing between a WS-derived row and a REST fill."""

    derived_trade_key: str
    exchange_trade_id: str
    exchange_entry_id: str
    ws_size: float
    rest_size: float
    ws_price: float
    rest_price: float


@dataclass
class ReconcileReport:
    """Outcome of one ``reconcile_order`` call.

    Attributes:
        client_order_id:    Order being reconciled.
        exchange_order_id:  Exchange-assigned order id used for the REST lookup.
        matched:            Pairings stamped onto fill_ledger as RECONCILED.
        ws_unmatched:       ``derived_trade_key`` values flagged MISMATCH
                            (present in fill_ledger but not in REST).
        rest_unmatched:     Raw REST fill dicts with no fill_ledger counterpart
                            (indicates a WS pipeline gap).
        rows_updated:       Total ``UPDATE fill_ledger`` rows persisted.
    """

    client_order_id: str
    exchange_order_id: str
    matched: List[ReconcileMatch] = field(default_factory=list)
    ws_unmatched: List[str] = field(default_factory=list)
    rest_unmatched: List[Dict[str, Any]] = field(default_factory=list)
    rows_updated: int = 0

    @property
    def is_clean(self) -> bool:
        """True when every WS row paired and no REST fills were left over."""
        return not self.ws_unmatched and not self.rest_unmatched


def _to_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class FillReconciler:
    """Pair WS-derived fill_ledger rows with authoritative REST fills."""

    def __init__(
        self,
        db_client,
        fills_fetcher: FillsFetcher,
        size_tolerance: float = DEFAULT_SIZE_TOLERANCE,
        price_tolerance_pct: float = DEFAULT_PRICE_TOLERANCE_PCT,
    ) -> None:
        """Args:
            db_client:           PostgresDB-shaped client with
                                 ``execute_query`` / ``execute_update``.
            fills_fetcher:       Callable mapping
                                 ``exchange_order_id -> list[REST fill dict]``.
                                 The dict shape matches
                                 ``GET /api/v3/brokerage/orders/historical/fills``.
            size_tolerance:      Absolute tolerance for matching sizes.
            price_tolerance_pct: Relative tolerance for matching prices.
        """
        self.db = db_client
        self.fills_fetcher = fills_fetcher
        self.size_tolerance = size_tolerance
        self.price_tolerance_pct = price_tolerance_pct

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def reconcile_order(
        self, client_order_id: str, exchange_order_id: str
    ) -> ReconcileReport:
        """Reconcile a single order's WS-derived rows against REST fills.

        Args:
            client_order_id:   Internal id used as the fill_ledger key.
            exchange_order_id: Exchange order id passed to the REST fetcher.

        Returns:
            A populated :class:`ReconcileReport`. Side effect: any matched
            rows have their ``exchange_trade_id``, ``exchange_entry_id``,
            ``reconciliation_status`` and ``reconciled_at`` columns updated;
            unmatched WS rows are flipped to ``MISMATCH``.
        """
        ws_rows = self._fetch_ws_rows(client_order_id)
        rest_fills = self._fetch_rest_fills(exchange_order_id)

        matched, ws_unmatched, rest_unmatched = self._greedy_match(
            ws_rows, rest_fills
        )

        rows_updated = 0
        rows_updated += self._apply_matched_updates(matched)
        rows_updated += self._apply_mismatch_updates(ws_unmatched)

        report = ReconcileReport(
            client_order_id=client_order_id,
            exchange_order_id=exchange_order_id,
            matched=matched,
            ws_unmatched=[r["derived_trade_key"] for r in ws_unmatched],
            rest_unmatched=rest_unmatched,
            rows_updated=rows_updated,
        )

        if report.is_clean:
            logger.info(
                "[RECONCILE] Order %s clean: %d match(es), 0 unmatched.",
                client_order_id,
                len(matched),
            )
        else:
            logger.warning(
                "[RECONCILE] Order %s drift: matched=%d ws_unmatched=%d rest_unmatched=%d",
                client_order_id,
                len(matched),
                len(report.ws_unmatched),
                len(report.rest_unmatched),
            )
        return report

    # ------------------------------------------------------------------
    # Data fetchers
    # ------------------------------------------------------------------

    def _fetch_ws_rows(self, client_order_id: str) -> List[Dict[str, Any]]:
        """Pull all WS-derived rows for one order in insertion order.

        Only ``WS_DERIVED`` rows are eligible; already-RECONCILED rows are
        immutable and already-MISMATCH rows require manual intervention.
        """
        query = """
            SELECT id, derived_trade_key, side, quantity, price, fees, timestamp
              FROM fill_ledger
             WHERE client_order_id = %s
               AND reconciliation_status = 'WS_DERIVED'
             ORDER BY id ASC
        """
        try:
            rows = self.db.execute_query(query, (client_order_id,)) or []
        except Exception as e:
            logger.error(
                "[RECONCILE] WS-row fetch failed for %s: %s: %s",
                client_order_id,
                type(e).__name__,
                e,
            )
            return []
        # Normalise numerics once so the matcher can compare floats directly.
        for row in rows:
            row["_size"] = _to_float(row.get("quantity"))
            row["_price"] = _to_float(row.get("price"))
        return rows

    def _fetch_rest_fills(self, exchange_order_id: str) -> List[Dict[str, Any]]:
        """Invoke the injected fetcher and normalise the result list."""
        try:
            raw = self.fills_fetcher(exchange_order_id) or []
        except Exception as e:
            logger.error(
                "[RECONCILE] REST fetcher failed for %s: %s: %s",
                exchange_order_id,
                type(e).__name__,
                e,
            )
            return []
        fills: List[Dict[str, Any]] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            fills.append({
                **item,
                "_size": _to_float(item.get("size")),
                "_price": _to_float(item.get("price")),
            })
        return fills

    # ------------------------------------------------------------------
    # Matching
    # ------------------------------------------------------------------

    def _greedy_match(
        self,
        ws_rows: List[Dict[str, Any]],
        rest_fills: List[Dict[str, Any]],
    ) -> Tuple[List[ReconcileMatch], List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Greedy size-then-price match.

        Strategy:
            For each WS row in insertion (chronological) order, scan the
            currently-unconsumed REST fills and pick the one whose size is
            within ``size_tolerance``. Among those, prefer the one whose
            price is within ``price_tolerance_pct``. The chosen REST fill is
            removed from further consideration.

        Returns ``(matched, ws_unmatched, rest_unmatched)``.
        """
        unconsumed = list(rest_fills)
        matched: List[ReconcileMatch] = []
        ws_unmatched: List[Dict[str, Any]] = []

        for ws in ws_rows:
            chosen_idx = self._best_rest_index(ws, unconsumed)
            if chosen_idx is None:
                ws_unmatched.append(ws)
                continue
            rest = unconsumed.pop(chosen_idx)
            matched.append(
                ReconcileMatch(
                    derived_trade_key=str(ws["derived_trade_key"]),
                    exchange_trade_id=str(rest.get("trade_id") or ""),
                    exchange_entry_id=str(rest.get("entry_id") or ""),
                    ws_size=ws["_size"],
                    rest_size=rest["_size"],
                    ws_price=ws["_price"],
                    rest_price=rest["_price"],
                )
            )

        return matched, ws_unmatched, unconsumed

    def _best_rest_index(
        self, ws: Dict[str, Any], candidates: List[Dict[str, Any]]
    ) -> Optional[int]:
        """Return the best-matching REST fill index for a WS row, or None."""
        best_idx: Optional[int] = None
        best_score = float("inf")
        ws_size = ws["_size"]
        ws_price = ws["_price"]
        ws_side = str(ws.get("side") or "").upper()

        for idx, rest in enumerate(candidates):
            if ws_side and str(rest.get("side") or "").upper() not in ("", ws_side):
                continue
            size_diff = abs(rest["_size"] - ws_size)
            if size_diff > self.size_tolerance:
                continue
            price_tolerance = max(
                abs(ws_price) * self.price_tolerance_pct,
                self.price_tolerance_pct,
            )
            price_diff = abs(rest["_price"] - ws_price)
            if price_diff > price_tolerance:
                continue
            # Composite score: size first, then price. Smaller is better.
            score = size_diff * 1e6 + price_diff
            if score < best_score:
                best_score = score
                best_idx = idx
        return best_idx

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _apply_matched_updates(self, matched: List[ReconcileMatch]) -> int:
        """Mark each matched row RECONCILED and stamp the exchange identifiers."""
        if not matched:
            return 0
        query = """
            UPDATE fill_ledger
               SET exchange_trade_id     = %s,
                   exchange_entry_id     = %s,
                   reconciliation_status = 'RECONCILED',
                   reconciled_at         = %s
             WHERE derived_trade_key     = %s
               AND reconciliation_status = 'WS_DERIVED'
        """
        now = datetime.utcnow()
        affected = 0
        for m in matched:
            try:
                rows = self.db.execute_update(
                    query,
                    (
                        m.exchange_trade_id or None,
                        m.exchange_entry_id or None,
                        now,
                        m.derived_trade_key,
                    ),
                )
                affected += int(rows or 0)
            except Exception as e:
                logger.error(
                    "[RECONCILE] UPDATE failed for derived_trade_key=%s: %s: %s",
                    m.derived_trade_key,
                    type(e).__name__,
                    e,
                )
        return affected

    def _apply_mismatch_updates(self, ws_unmatched: List[Dict[str, Any]]) -> int:
        """Flag every WS row with no REST counterpart as MISMATCH."""
        if not ws_unmatched:
            return 0
        query = """
            UPDATE fill_ledger
               SET reconciliation_status = 'MISMATCH',
                   reconciled_at         = %s
             WHERE derived_trade_key     = %s
               AND reconciliation_status = 'WS_DERIVED'
        """
        now = datetime.utcnow()
        affected = 0
        for row in ws_unmatched:
            key = row.get("derived_trade_key")
            if not key:
                continue
            try:
                rows = self.db.execute_update(query, (now, key))
                affected += int(rows or 0)
            except Exception as e:
                logger.error(
                    "[RECONCILE] MISMATCH UPDATE failed for derived_trade_key=%s: %s: %s",
                    key,
                    type(e).__name__,
                    e,
                )
        return affected
