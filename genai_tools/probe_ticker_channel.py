"""Probe Coinbase WS ticker channel for derivatives products.

Subscribes to all configured products on the ``ticker`` channel and
reports which product_ids actually receive updates within a fixed
window. Settles the question: does Coinbase publish public-channel
ticker data for CDE futures, or does the subscription silently drop?

Usage:
    .\\.venv\\Scripts\\python.exe genai_tools\\probe_ticker_channel.py [--seconds 30]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from threading import Lock

from coinbase.websocket import WSClient

from configuration import (
    API_KEY,
    API_SECRET,
    DERIVATIVES_PRODUCT_IDS,
    SPOT_PRODUCT_IDS,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=int, default=20)
    args = parser.parse_args()

    counts: Counter = Counter()
    first_seen: dict = {}
    raw_event_counter = Counter()
    lock = Lock()
    start = time.time()

    def on_message(message_str: str) -> None:
        try:
            msg = json.loads(message_str)
        except Exception:
            return
        channel = msg.get("channel")
        with lock:
            raw_event_counter[channel] += 1
        if channel != "ticker":
            return
        for evt in msg.get("events", []) or []:
            for tickr in evt.get("tickers", []) or []:
                pid = tickr.get("product_id")
                if not pid:
                    continue
                with lock:
                    counts[pid] += 1
                    first_seen.setdefault(pid, round(time.time() - start, 2))

    products = list(DERIVATIVES_PRODUCT_IDS) + list(SPOT_PRODUCT_IDS)
    print(f"Subscribing to {len(products)} products on 'ticker' channel:")
    for p in products:
        print(f"  - {p}")
    print()

    client = WSClient(
        verbose=False,
        api_key=API_KEY,
        api_secret=API_SECRET,
        on_message=on_message,
    )
    client.open()
    client.subscribe(product_ids=products, channels=["ticker"])

    try:
        deadline = time.time() + args.seconds
        while time.time() < deadline:
            time.sleep(0.5)
    finally:
        try:
            client.unsubscribe(product_ids=products, channels=["ticker"])
        except Exception:
            pass
        try:
            client.close()
        except Exception:
            pass

    print("\n=== RAW EVENT COUNTS BY CHANNEL ===")
    for ch, n in raw_event_counter.most_common():
        print(f"  {ch:20s} {n}")

    print("\n=== TICKER UPDATES PER PRODUCT ===")
    for pid in products:
        n = counts.get(pid, 0)
        first = first_seen.get(pid, "—")
        flag = "OK " if n > 0 else "MISS"
        print(f"  [{flag}] {pid:25s} ticks={n:5d}  first_at_s={first}")

    missing = [p for p in products if counts.get(p, 0) == 0]
    if missing:
        print(f"\nNO TICKS for {len(missing)}/{len(products)}: {missing}")
        return 1
    print("\nAll products received at least one ticker update.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
