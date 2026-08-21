"""Inspect XTZ-USD and BTC-USDC fills from last 24h to figure out why
they show commissions when the user didn't trade them."""
from datetime import datetime, timedelta, timezone
from configuration import REST_CLIENT

until = datetime.now(timezone.utc)
since = until - timedelta(hours=24)
since_iso = since.replace(microsecond=0).isoformat().replace("+00:00", "Z")
until_iso = until.replace(microsecond=0).isoformat().replace("+00:00", "Z")

for pid in ("XTZ-USD", "BTC-USDC", "DNT-USD", "ETH-USD", "BTC-USD"):
    print(f"\n=== {pid} ===")
    cursor = None
    n = 0
    sample = None
    times = []
    order_ids = set()
    while True:
        resp = REST_CLIENT.list_fills(
            start_date=since_iso, end_date=until_iso,
            product_id=pid, cursor=cursor, limit=100,
        )
        fills = resp.get("fills", []) or []
        for f in fills:
            n += 1
            if sample is None:
                sample = f
            times.append(f.get("trade_time"))
            order_ids.add(f.get("order_id"))
        cursor = resp.get("cursor") or None
        if not cursor or resp.get("has_next") is False:
            break
    print(f"  fills: {n}, distinct order_ids: {len(order_ids)}")
    if times:
        print(f"  earliest: {min(times)}")
        print(f"  latest:   {max(times)}")
    if sample:
        print(f"  sample fill: {sample}")
