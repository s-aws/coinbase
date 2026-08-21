"""Phase-1 measurement: stream Binance USDT-M perp bookTicker for
configured symbols, log per-symbol tick rate + spread, and (when
Coinbase mid is provided via stdin or a stub) print the rolling
``coinbase_premium_bps`` so we can eyeball whether the signal is
worth wiring into reveal logic.

This is a *measurement-only* tool. It does not touch the engine,
the database, or any pricing logic. Run it standalone:

    py -3.13 genai_tools/measure_cross_venue_lead_lag.py

Stop with Ctrl+C. Summary stats are printed every ``--interval``
seconds (default 10).

For the full Phase-1 plan see the chat thread / repo notes — this
script's job is just to answer "is the cross-venue feed live and
stable, and how does its mid relate to ours?"
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import threading
import time
from collections import defaultdict
from typing import Dict

# Make the script runnable from repo root without an editable install
# already being active.
import os
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from external.binance_perp_ws import BinancePerpTickerClient
from market_intel.cross_venue_aggregator import CrossVenueAggregator
from market_intel.venues import (
    COINBASE_TO_EXTERNAL,
    Venue,
    all_subscribed_symbols,
)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--interval", type=float, default=10.0,
        help="Seconds between summary prints (default 10).",
    )
    p.add_argument(
        "--symbols", default=None,
        help=(
            "Comma-separated subset of Binance symbols to subscribe. "
            "Default = every symbol referenced by the Coinbase product "
            "mapping table."
        ),
    )
    p.add_argument(
        "--debug-frames", action="store_true",
        help="Log every parsed bookTicker payload (very chatty).",
    )
    return p


def main() -> int:
    args = _build_parser().parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    logger = logging.getLogger("measure_cross_venue")

    if args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    else:
        symbols = all_subscribed_symbols(Venue.BINANCE_PERP)

    if not symbols:
        print(
            "No symbols configured for BINANCE_PERP. Add entries to "
            "market_intel/venues.COINBASE_TO_EXTERNAL.",
            file=sys.stderr,
        )
        return 2

    aggregator = CrossVenueAggregator()

    # Frame counter (one per (venue, symbol) increment).
    counts: Dict[str, int] = defaultdict(int)
    counts_lock = threading.Lock()

    def debug_cb(data: dict) -> None:
        sym = data.get("s")
        if not sym:
            return
        with counts_lock:
            counts[sym] += 1
        if args.debug_frames:
            logger.info("frame %s bid=%s ask=%s", sym, data.get("b"), data.get("a"))

    client = BinancePerpTickerClient(
        aggregator,
        symbols=symbols,
        debug_callback=debug_cb,
    )
    client.start()

    stop = threading.Event()

    def _on_signal(*_):
        stop.set()

    signal.signal(signal.SIGINT, _on_signal)
    try:
        signal.signal(signal.SIGTERM, _on_signal)
    except (AttributeError, ValueError):
        # Windows / non-main-thread: SIGTERM isn't installable.
        pass

    last_counts: Dict[str, int] = defaultdict(int)
    try:
        while not stop.is_set():
            # Use a bounded wait so SIGINT is observed promptly on
            # Windows (Event.wait without timeout is uninterruptible
            # by console signals — see /memories/windows-signal-event-wait.md).
            stop.wait(timeout=args.interval)
            if stop.is_set():
                break

            with counts_lock:
                snapshot = dict(counts)

            print()
            print(f"--- summary @ {time.strftime('%Y-%m-%d %H:%M:%S')} ---")
            for sym in sorted(symbols):
                total = snapshot.get(sym, 0)
                delta = total - last_counts.get(sym, 0)
                rate = delta / max(args.interval, 0.001)
                last_counts[sym] = total
                latest = aggregator.latest_tick(Venue.BINANCE_PERP, sym)
                if latest is None:
                    print(f"  {sym}: no ticks yet (count={total})")
                    continue
                print(
                    f"  {sym}: {rate:6.1f} ticks/s "
                    f"mid={latest.mid:>12.4f} spread={latest.spread_bps:5.2f} bps "
                    f"(total={total})"
                )

            # Per-Coinbase-product intel summary (no Coinbase mid input
            # in this measurement build — premium will be None).
            print("  Coinbase-product consensus (no live CB mid wired):")
            for cb_product in sorted(COINBASE_TO_EXTERNAL.keys()):
                intel = aggregator.get_intel(cb_product)
                if intel is None or intel.consensus_mid is None:
                    continue
                proxy_flag = " (proxy)" if intel.used_proxy else ""
                disp = (
                    f"{intel.cross_venue_dispersion_bps:.2f} bps"
                    if intel.cross_venue_dispersion_bps is not None else "n/a"
                )
                print(
                    f"    {cb_product:24s} consensus={intel.consensus_mid:>12.4f} "
                    f"fresh_venues={intel.fresh_venue_count} "
                    f"dispersion={disp}{proxy_flag}"
                )
    finally:
        print("\nstopping...")
        client.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
