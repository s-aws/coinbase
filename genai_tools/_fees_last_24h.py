r"""Sum total commissions paid in the last 24h via REST list_fills.

Run from repo root:
    .\.venv\Scripts\python.exe genai_tools\_fees_last_24h.py
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from configuration import REST_CLIENT


def main() -> None:
    until = datetime.now(timezone.utc)
    since = until - timedelta(hours=24)
    # Coinbase wants ISO-8601 with trailing "Z" for UTC.
    since_iso = since.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    until_iso = until.replace(microsecond=0).isoformat().replace("+00:00", "Z")

    print(f"Window: {since_iso}  ->  {until_iso}")

    total_fee = Decimal("0")
    total_commission = Decimal("0")
    fill_count = 0
    by_product: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    by_currency: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))

    cursor = None
    page = 0
    while True:
        page += 1
        resp = REST_CLIENT.list_fills(
            start_date=since_iso,
            end_date=until_iso,
            cursor=cursor,
            limit=100,
        )
        fills = resp.get("fills", []) or []
        for f in fills:
            fill_count += 1
            fee = Decimal(str(f.get("fee") or "0"))
            commission = Decimal(str(f.get("commission") or "0"))
            total_fee += fee
            total_commission += commission
            pid = f.get("product_id") or "<unknown>"
            by_product[pid] += commission
            ccy = f.get("settlement_currency") or "<unknown>"
            by_currency[ccy] += commission

        cursor = resp.get("cursor") or None
        has_next = resp.get("has_next")
        if not cursor or has_next is False:
            break
        if page > 5000:
            print("WARN: stopped after 5000 pages")
            break

    print(f"Pages fetched:    {page}")
    print(f"Fills in window:  {fill_count}")
    print(f"Sum of `fee`:        {total_fee}")
    print(f"Sum of `commission`: {total_commission}")

    print("\nBy settlement_currency:")
    for ccy, amt in sorted(by_currency.items(), key=lambda kv: -kv[1]):
        print(f"  {ccy:>6}  {amt}")

    print("\nBy product (commission):")
    for pid, amt in sorted(by_product.items(), key=lambda kv: -kv[1]):
        print(f"  {pid:<24} {amt}")


if __name__ == "__main__":
    main()
