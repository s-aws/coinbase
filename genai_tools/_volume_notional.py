"""Total volume + notional from REST list_fills for last 24h and last 30d.

For each window we report:
  - fill count
  - total contracts/units traded (sum of fill.size)
  - raw notional   = sum(size * price)             (size and price as reported)
  - true notional  = raw_notional * contract_size  (futures only; for spot
                     contract_size = 1 so the two are identical)

Coinbase reports ``size`` for futures in CONTRACTS (not the underlying),
so notional is only meaningful after multiplying by the per-product
``future_product_details.contract_size``.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from configuration import REST_CLIENT


def _summarize(label: str, since_iso: str, until_iso: str) -> None:
    print(f"\n========== {label} ==========")
    print(f"Window: {since_iso}  ->  {until_iso}")

    fill_count = 0
    by_product: dict[str, dict] = defaultdict(
        lambda: {
            "fills": 0,
            "size": Decimal("0"),
            "raw_notional": Decimal("0"),
            "buy_size": Decimal("0"),
            "sell_size": Decimal("0"),
        }
    )

    cursor = None
    page = 0
    while True:
        page += 1
        resp = REST_CLIENT.list_fills(
            start_date=since_iso, end_date=until_iso,
            cursor=cursor, limit=100,
        )
        for f in resp.get("fills", []) or []:
            fill_count += 1
            pid = f.get("product_id") or "<unknown>"
            size = Decimal(str(f.get("size") or "0"))
            price = Decimal(str(f.get("price") or "0"))
            side = (f.get("side") or "").upper()
            row = by_product[pid]
            row["fills"] += 1
            row["size"] += size
            row["raw_notional"] += size * price
            if side == "BUY":
                row["buy_size"] += size
            elif side == "SELL":
                row["sell_size"] += size
        cursor = resp.get("cursor") or None
        if not cursor or resp.get("has_next") is False:
            break
        if page > 5000:
            print("WARN stopped after 5000 pages")
            break

    # Fetch contract_size for each product (futures need it; spot returns 1).
    contract_sizes: dict[str, Decimal] = {}
    for pid in by_product:
        try:
            pdict = REST_CLIENT.get_product_dict(pid) or {}
        except Exception:
            pdict = {}
        cs_raw = (pdict.get("future_product_details") or {}).get("contract_size")
        contract_sizes[pid] = Decimal(str(cs_raw)) if cs_raw else Decimal("1")

    print(f"Pages: {page}, fills: {fill_count}")

    # Totals
    total_raw = sum((r["raw_notional"] for r in by_product.values()), Decimal("0"))
    total_true = sum(
        (r["raw_notional"] * contract_sizes[pid] for pid, r in by_product.items()),
        Decimal("0"),
    )
    print(f"Total raw notional   (contracts*price)        = {total_raw}")
    print(f"Total true notional  (raw * contract_size)    = {total_true}")

    print(f"\n{'product':<24} {'fills':>6} {'csize':>8} "
          f"{'contracts':>16} {'buy':>14} {'sell':>14} "
          f"{'raw_notional':>20} {'true_notional':>20}")
    for pid, r in sorted(
        by_product.items(),
        key=lambda kv: -(kv[1]["raw_notional"] * contract_sizes[kv[0]]),
    ):
        cs = contract_sizes[pid]
        true_not = r["raw_notional"] * cs
        print(
            f"{pid:<24} {r['fills']:>6} {str(cs):>8} "
            f"{str(r['size']):>16} {str(r['buy_size']):>14} {str(r['sell_size']):>14} "
            f"{str(r['raw_notional']):>20} {str(true_not):>20}"
        )


def main() -> None:
    until = datetime.now(timezone.utc)
    for label, delta in (("LAST 24h", timedelta(hours=24)),
                         ("LAST 30d", timedelta(days=30))):
        since = until - delta
        since_iso = since.replace(microsecond=0).isoformat().replace("+00:00", "Z")
        until_iso = until.replace(microsecond=0).isoformat().replace("+00:00", "Z")
        _summarize(label, since_iso, until_iso)


if __name__ == "__main__":
    main()
