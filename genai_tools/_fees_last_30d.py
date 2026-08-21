"""Sum total commissions paid in the last 30 days via REST list_fills."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from configuration import REST_CLIENT


def main() -> None:
    until = datetime.now(timezone.utc)
    since = until - timedelta(days=30)
    since_iso = since.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    until_iso = until.replace(microsecond=0).isoformat().replace("+00:00", "Z")

    print(f"Window: {since_iso}  ->  {until_iso}")

    total_commission = Decimal("0")
    fill_count = 0
    by_product: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    by_day: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))

    cursor = None
    page = 0
    while True:
        page += 1
        resp = REST_CLIENT.list_fills(
            start_date=since_iso, end_date=until_iso,
            cursor=cursor, limit=100,
        )
        fills = resp.get("fills", []) or []
        for f in fills:
            fill_count += 1
            commission = Decimal(str(f.get("commission") or "0"))
            total_commission += commission
            pid = f.get("product_id") or "<unknown>"
            by_product[pid] += commission
            ts = f.get("trade_time") or ""
            day = ts[:10] if ts else "<unknown>"
            by_day[day] += commission
        cursor = resp.get("cursor") or None
        if not cursor or resp.get("has_next") is False:
            break
        if page > 5000:
            print("WARN: stopped after 5000 pages")
            break

    print(f"Pages fetched:    {page}")
    print(f"Fills in window:  {fill_count}")
    print(f"Total commission: {total_commission}")

    print("\nBy product:")
    for pid, amt in sorted(by_product.items(), key=lambda kv: -kv[1]):
        print(f"  {pid:<24} {amt}")

    print("\nBy day:")
    for day, amt in sorted(by_day.items()):
        print(f"  {day}  {amt}")


if __name__ == "__main__":
    main()
