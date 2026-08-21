"""Backfill 1-minute OHLC candles into ``market_candle_1m``.

Pulls historical candles via the Coinbase REST API for each product the
engine is configured to trade, paging in <=350-candle windows (Coinbase's
per-call cap), and upserts them into ``market_candle_1m``.

Usage (from repo root, with venv active):

    python -m genai_tools.backfill_candles               # last 24h, all products
    python -m genai_tools.backfill_candles --hours 48    # last 48h
    python -m genai_tools.backfill_candles --products BIT-29MAY26-CDE BIP-20DEC30-CDE
    python -m genai_tools.backfill_candles --dry-run     # show plan, no writes

Re-runs are safe: ``upsert_candles`` does ``ON CONFLICT DO UPDATE``.

This script lives in ``genai_tools/`` because it's an operator-driven
seed/maintenance task, not part of the engine's runtime path.
"""

from __future__ import annotations

import argparse
import sys
import time
from typing import List

# Allow `python -m genai_tools.backfill_candles` from repo root.
import os
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from logging_service import get_logger
from configuration import REST_CLIENT, DERIVATIVES_PRODUCT_IDS, SPOT_PRODUCT_IDS
from database.market_candle_store import upsert_candles

logger = get_logger("BackfillCandles")

# Coinbase caps each get_candles call at 350 candles. At 1-minute
# granularity that is 350 minutes. Pick a slightly conservative chunk
# size to leave headroom and keep the math obvious.
_CHUNK_MINUTES = 300


def _parse_args(argv: List[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--hours", type=float, default=24.0,
        help="Lookback window in hours (default: 24).",
    )
    p.add_argument(
        "--products", nargs="*", default=None,
        help=(
            "Restrict to specific product ids. Default: all configured "
            "DERIVATIVES + SPOT products."
        ),
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="Print the per-product plan without contacting the API or DB.",
    )
    return p.parse_args(argv)


def _resolve_products(requested: List[str] | None) -> List[str]:
    if requested:
        return list(requested)
    return list(DERIVATIVES_PRODUCT_IDS) + list(SPOT_PRODUCT_IDS)


def _backfill_product(product_id: str, start: int, end: int, dry_run: bool) -> int:
    """Page through ``[start, end]`` in <=300-minute chunks; returns row count."""
    chunk_seconds = _CHUNK_MINUTES * 60
    cursor = start
    total = 0
    chunks = 0
    while cursor < end:
        window_end = min(cursor + chunk_seconds, end)
        chunks += 1
        if dry_run:
            logger.info(
                f"[dry-run] {product_id}: would fetch [{cursor}..{window_end}] "
                f"(~{(window_end - cursor) // 60} candles)"
            )
        else:
            try:
                candles = REST_CLIENT.get_candles(
                    product_id=product_id,
                    start=cursor,
                    end=window_end,
                    granularity="ONE_MINUTE",
                )
            except Exception as e:
                logger.warning(
                    f"{product_id}: get_candles failed for "
                    f"[{cursor}..{window_end}]: {type(e).__name__}: {e}"
                )
                cursor = window_end
                continue
            written = upsert_candles(product_id, candles)
            total += written
            logger.info(
                f"{product_id}: chunk {chunks} "
                f"[{cursor}..{window_end}] -> {len(candles)} fetched, "
                f"{written} upserted"
            )
        cursor = window_end
    return total


def main(argv: List[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    end = int(time.time())
    start = end - int(args.hours * 3600)
    products = _resolve_products(args.products)

    logger.info(
        f"Backfill plan: {len(products)} product(s), "
        f"window {args.hours}h, granularity ONE_MINUTE, "
        f"chunk {_CHUNK_MINUTES} minutes/call"
    )

    grand_total = 0
    for pid in products:
        try:
            grand_total += _backfill_product(pid, start, end, args.dry_run)
        except Exception as e:
            logger.error(f"{pid}: backfill aborted: {type(e).__name__}: {e}")

    logger.info(f"Done. Total candles upserted: {grand_total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
